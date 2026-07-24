"""OpenAI Chat Completions backend.

Works with **any** OpenAI-compatible API: OpenAI itself, OpenRouter, Groq,
Together, DeepSeek, Mistral, Fireworks, LM Studio, vLLM, llama.cpp server or a
corporate gateway. Point ``base_url`` at the endpoint and, if the provider
needs them, add custom ``headers``.
"""

from __future__ import annotations

import json
from typing import Any

from .base import LLMBackend, LLMResponse, ToolCall


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

    # ------------------------------------------------------------------
    @classmethod
    def from_provider(cls, provider) -> "OpenAIBackend":
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
    def chat(self, messages, tools=None) -> LLMResponse:
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

        completion = self.client.chat.completions.create(**kwargs)
        choice = completion.choices[0].message

        tool_calls: list[ToolCall] = []
        for tc in choice.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            if not isinstance(args, dict):
                args = {"_raw": args}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        return LLMResponse(content=choice.content, tool_calls=tool_calls)
