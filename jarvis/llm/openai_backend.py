"""OpenAI Chat Completions backend.

Works with **any** OpenAI-compatible API: OpenAI itself, OpenRouter, Groq,
Together, DeepSeek, Mistral, Fireworks, NVIDIA NIM, LM Studio, vLLM,
llama.cpp server or a corporate gateway. Point ``base_url`` at the endpoint
and, if the provider needs them, add custom ``headers``.

Requests are retried on timeouts and throttling, and every call is metered by
the budget tracker.

Not every endpoint answers in the shape the OpenAI SDK documents. Reasoning
models served through NVIDIA NIM (GLM, DeepSeek-R1, QwQ) put their answer in
``reasoning_content`` and leave ``content`` empty; some gateways return a list
of content parts. Reading only ``content`` turned those replies into silence,
so :func:`extract_content` handles all three shapes and explains the two cases
where there really is nothing to show.
"""

from __future__ import annotations

import json
from typing import Any

from ..budget import BudgetTracker, default_tracker, estimate_tokens, usage_from_openai
from ..retry import call_with_retry
from .base import LLMBackend, LLMResponse, ToolCall

#: Fields reasoning models use instead of ``content``.
REASONING_FIELDS = ("reasoning_content", "reasoning")

#: Shown when the model ran out of tokens before writing anything.
TRUNCATED_NOTE = (
    "The model hit its token limit before it produced an answer. "
    "Raise max_tokens for this provider in config.yaml and ask again."
)

#: Shown when the endpoint answered with an empty message and no tool call.
EMPTY_NOTE = (
    "The provider returned an empty message. This usually means the model name "
    "is wrong for this endpoint, or the endpoint answered in an unexpected "
    "shape. Run 'jarvis --doctor' to check the provider, model and key."
)


def _text_of(part: Any) -> str:
    """Return the text of a single content part, whatever shape it has."""

    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        return str(part.get("text") or "")
    return str(getattr(part, "text", "") or "")


def _field(message: Any, name: str) -> Any:
    """Read ``name`` from the message, including undocumented extra fields."""

    value = getattr(message, name, None)
    if value is None:
        extra = getattr(message, "model_extra", None) or {}
        if isinstance(extra, dict):
            value = extra.get(name)
    return value


def extract_content(message: Any, finish_reason: str = "") -> str:
    """Return the text of an assistant message, or an explanation of its absence.

    Returns an empty string only when the message is genuinely empty and the
    reason is unknown — the caller decides what to do with that.
    """

    content = getattr(message, "content", None)
    if isinstance(content, (list, tuple)):
        content = "".join(_text_of(part) for part in content)
    if content and str(content).strip():
        return str(content)

    for name in REASONING_FIELDS:
        value = _field(message, name)
        if value and str(value).strip():
            return str(value)

    if finish_reason == "length":
        return TRUNCATED_NOTE
    return ""


class OpenAIBackend(LLMBackend):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        headers: dict[str, str] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
        timeout: int = 180,
        provider_name: str = "",
        budget: BudgetTracker | None = None,
    ):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "The 'openai' package is required. Install with `pip install openai`."
            ) from exc

        # Local servers (LM Studio, vLLM, llama.cpp) usually need no real key.
        if not api_key:
            if not base_url:
                raise ValueError(
                    "No API key set. Provide one, or set a base_url for a local/keyless endpoint."
                )
            api_key = "not-needed"

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or None,
            default_headers=headers or None,
            timeout=timeout,
        )
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_body = extra_body or {}
        self.provider_name = provider_name or self.name
        self.budget = budget or default_tracker()

    # ------------------------------------------------------------------
    @classmethod
    def from_provider(cls, provider) -> OpenAIBackend:
        """Build a backend from a :class:`jarvis.config.ProviderConfig`."""

        return cls(
            api_key=provider.api_key,
            model=provider.model or "gpt-4o-mini",
            base_url=provider.base_url or None,
            headers=provider.headers or None,
            temperature=provider.temperature,
            max_tokens=provider.max_tokens,
            extra_body=provider.extra_body,
            timeout=provider.timeout,
            provider_name=getattr(provider, "name", "") or "",
        )

    # ------------------------------------------------------------------
    def _to_openai_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for msg in messages:
            role = msg["role"]
            if role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg["tool_call_id"],
                        "content": msg["content"],
                    }
                )
            elif role == "assistant" and msg.get("tool_calls"):
                out.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                                },
                            }
                            for tc in msg["tool_calls"]
                        ],
                    }
                )
            else:
                out.append({"role": role, "content": msg.get("content", "")})
        return out

    @staticmethod
    def _to_openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in tools
        ]

    # ------------------------------------------------------------------
    def _meter(self, completion: Any, messages: list[dict[str, Any]], reply: str | None) -> None:
        prompt_tokens, completion_tokens = usage_from_openai(completion)
        if not prompt_tokens:
            prompt_tokens = sum(
                estimate_tokens(str(m.get("content") or "")) for m in messages
            )
        if not completion_tokens:
            completion_tokens = estimate_tokens(reply or "")
        self.budget.record(self.provider_name, self.model, prompt_tokens, completion_tokens)

    def chat(self, messages, tools=None) -> LLMResponse:
        self.budget.check()

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_openai_messages(messages),
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body

        openai_tools = self._to_openai_tools(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        completion = call_with_retry(
            lambda: self.client.chat.completions.create(**kwargs),
            description=f"OpenAI-compatible request to {self.model}",
        )
        first = completion.choices[0]
        choice = first.message
        finish_reason = getattr(first, "finish_reason", "") or ""

        tool_calls: list[ToolCall] = []
        for tc in choice.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            if not isinstance(args, dict):
                args = {"_raw": args}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        content = extract_content(choice, finish_reason)
        self._meter(completion, messages, content)
        if not content and not tool_calls:
            # Silence is the one answer the user cannot act on.
            content = EMPTY_NOTE
        return LLMResponse(content=content, tool_calls=tool_calls)
