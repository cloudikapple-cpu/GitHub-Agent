"""Anthropic (Claude) backend.

Requests are retried on timeouts and throttling, and every call is metered by
the budget tracker.
"""

from __future__ import annotations

from typing import Any

from ..budget import BudgetTracker, default_tracker, estimate_tokens, usage_from_anthropic
from ..retry import call_with_retry
from .base import LLMBackend, LLMResponse, ToolCall


class AnthropicBackend(LLMBackend):
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-latest",
        max_tokens: int = 4096,
        budget: BudgetTracker | None = None,
    ):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set.")
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "The 'anthropic' package is required. Install with `pip install anthropic`."
            ) from exc

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.budget = budget or default_tracker()

    # ------------------------------------------------------------------
    def _split_messages(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        """Return (system_prompt, anthropic_messages)."""
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []

        for msg in messages:
            role = msg["role"]
            if role == "system":
                if msg.get("content"):
                    system_parts.append(msg["content"])
            elif role == "tool":
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg["tool_call_id"],
                                "content": msg["content"],
                            }
                        ],
                    }
                )
            elif role == "assistant" and msg.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if msg.get("content"):
                    blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                converted.append({"role": "assistant", "content": blocks})
            else:
                converted.append({"role": role, "content": msg.get("content", "")})

        return "\n\n".join(system_parts), converted

    @staticmethod
    def _to_anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"],
            }
            for t in tools
        ]

    # ------------------------------------------------------------------
    def _meter(self, response: Any, messages: list[dict[str, Any]], reply: str | None) -> None:
        prompt_tokens, completion_tokens = usage_from_anthropic(response)
        if not prompt_tokens:
            prompt_tokens = sum(
                estimate_tokens(str(m.get("content") or "")) for m in messages
            )
        if not completion_tokens:
            completion_tokens = estimate_tokens(reply or "")
        self.budget.record(self.name, self.model, prompt_tokens, completion_tokens)

    def chat(self, messages, tools=None) -> LLMResponse:
        self.budget.check()

        system_prompt, anthropic_messages = self._split_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": anthropic_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        anthropic_tools = self._to_anthropic_tools(tools)
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        response = call_with_retry(
            lambda: self.client.messages.create(**kwargs),
            description=f"Anthropic request to {self.model}",
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )

        content = "\n".join(text_parts) if text_parts else None
        self._meter(response, messages, content)
        return LLMResponse(content=content, tool_calls=tool_calls)
