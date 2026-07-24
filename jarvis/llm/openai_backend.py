"""OpenAI Chat Completions backend (works with any OpenAI-compatible API)."""

from __future__ import annotations

import json
from typing import Any

from .base import LLMBackend, LLMResponse, ToolCall


class OpenAIBackend(LLMBackend):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", base_url: str | None = None):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set.")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ImportError("The 'openai' package is required. Install with `pip install openai`.") from exc

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

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
                                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
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
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        return LLMResponse(content=choice.content, tool_calls=tool_calls)
