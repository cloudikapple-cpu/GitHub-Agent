"""Local model backend served through Ollama (https://ollama.com).

Uses Ollama's OpenAI-style ``/api/chat`` endpoint, which supports tool calling
for models that advertise the capability (e.g. llama3.1, qwen2.5, mistral-nemo).
No API key is required — the model runs on the user's own machine.
"""

from __future__ import annotations

import uuid
from typing import Any

import requests

from .base import LLMBackend, LLMResponse, ToolCall


class OllamaBackend(LLMBackend):
    name = "ollama"

    def __init__(self, host: str = "http://localhost:11434", model: str = "llama3.1", timeout: int = 300):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    # ------------------------------------------------------------------
    def _to_ollama_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for msg in messages:
            role = msg["role"]
            if role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "content": msg["content"],
                        "tool_name": msg.get("name", ""),
                    }
                )
            elif role == "assistant" and msg.get("tool_calls"):
                out.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or "",
                        "tool_calls": [
                            {"function": {"name": tc.name, "arguments": tc.arguments}}
                            for tc in msg["tool_calls"]
                        ],
                    }
                )
            else:
                out.append({"role": role, "content": msg.get("content", "")})
        return out

    @staticmethod
    def _to_ollama_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
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
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_ollama_messages(messages),
            "stream": False,
        }
        ollama_tools = self._to_ollama_tools(tools)
        if ollama_tools:
            payload["tools"] = ollama_tools

        try:
            resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.host}. Is it running (`ollama serve`)? Details: {exc}"
            ) from exc

        message = resp.json().get("message", {})
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            arguments = fn.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {"_raw": arguments}
            tool_calls.append(ToolCall(id=uuid.uuid4().hex, name=fn.get("name", ""), arguments=arguments))

        content = message.get("content") or None
        return LLMResponse(content=content, tool_calls=tool_calls)
