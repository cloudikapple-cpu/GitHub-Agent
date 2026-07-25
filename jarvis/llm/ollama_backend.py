"""Local model backend served through Ollama (https://ollama.com).

Ollama runs the model on this machine, so nothing leaves it and every call
costs zero -- the ledger still records the tokens so local and cloud usage can
be compared. The backend speaks Ollama's native ``/api/chat`` endpoint, which
supports tool calling for models that advertise it (llama3.1, qwen2.5,
mistral-nemo, ...) and image input for vision models (llava, llama3.2-vision).

Streaming is real: ``/api/chat`` answers with newline-delimited JSON and each
line is pushed to the sink as it arrives, tool call fragments included.

Typical setup::

    ollama serve
    ollama pull llama3.1
    jarvis --backend ollama
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import requests

from ..budget import BudgetTracker, default_tracker, estimate_tokens
from ..retry import call_with_retry
from .base import LLMBackend, LLMResponse, ToolCall

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1"

#: Name fragments of models that can look at images.
VISION_HINTS = (
    "llava",
    "bakllava",
    "moondream",
    "vision",
    "minicpm-v",
    "qwen2-vl",
    "qwen2.5vl",
    "gemma3",
)

#: Shown whenever the server cannot be reached, because 'connection refused'
#: on its own never told anybody what to do next.
START_HINT = (
    "Start it with `ollama serve`, then pull a model: `ollama pull {model}`. "
    "Downloads and setup: https://ollama.com/download"
)


def looks_like_vision_model(model: str) -> bool:
    """Guess whether ``model`` can read images from its name."""

    lowered = (model or "").lower()
    return any(hint in lowered for hint in VISION_HINTS)


class OllamaBackend(LLMBackend):
    """Talk to a local Ollama server."""

    name = "ollama"
    supports_streaming = True

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        model: str = DEFAULT_MODEL,
        timeout: int = 300,
        budget: BudgetTracker | None = None,
        options: dict[str, Any] | None = None,
        keep_alive: str = "5m",
        vision: bool | None = None,
        provider_name: str = "ollama",
    ):
        self.host = (host or DEFAULT_HOST).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self.budget = budget or default_tracker()
        #: Sampling options passed straight to Ollama (temperature, num_ctx, ...).
        self.options = dict(options or {})
        #: How long the model stays loaded in memory after the call.
        self.keep_alive = keep_alive
        self.provider_name = provider_name or "ollama"
        self.supports_vision = (
            looks_like_vision_model(self.model) if vision is None else bool(vision)
        )

    # ------------------------------------------------------------------
    @classmethod
    def from_provider(cls, provider) -> OllamaBackend:
        """Build a backend from a :class:`jarvis.config.ProviderConfig`.

        ``temperature`` and ``max_tokens`` are translated into the Ollama
        option names, and anything in ``extra_body`` is merged on top, so an
        unusual knob such as ``num_ctx`` can be set from config.yaml without a
        code change.
        """

        options: dict[str, Any] = {}
        if getattr(provider, "temperature", None) is not None:
            options["temperature"] = provider.temperature
        max_tokens = getattr(provider, "max_tokens", 0)
        if max_tokens:
            options["num_predict"] = int(max_tokens)
        extra = dict(getattr(provider, "extra_body", {}) or {})
        keep_alive = str(extra.pop("keep_alive", "5m"))
        options.update(extra.pop("options", {}) or {})
        options.update(extra)
        return cls(
            host=getattr(provider, "base_url", "") or DEFAULT_HOST,
            model=getattr(provider, "model", "") or DEFAULT_MODEL,
            timeout=int(getattr(provider, "timeout", 300) or 300),
            options=options,
            keep_alive=keep_alive,
            vision=True if getattr(provider, "vision", False) else None,
            provider_name=getattr(provider, "name", "ollama") or "ollama",
        )

    # ------------------------------------------------------------------
    def _to_ollama_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for msg in messages:
            role = msg["role"]
            if role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "content": msg.get("content", ""),
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
                entry: dict[str, Any] = {"role": role, "content": msg.get("content", "") or ""}
                images = msg.get("images")
                if images:
                    # Ollama takes raw base64 strings, without the data: prefix.
                    entry["images"] = [str(image).split(",")[-1] for image in images]
                out.append(entry)
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

    def _payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_ollama_messages(messages),
            "stream": stream,
            "keep_alive": self.keep_alive,
        }
        if self.options:
            payload["options"] = dict(self.options)
        ollama_tools = self._to_ollama_tools(tools)
        if ollama_tools:
            payload["tools"] = ollama_tools
            # Tool calls arrive in one piece, so streaming them adds nothing but
            # a class of parsing bugs.
            payload["stream"] = False
        return payload

    def _unreachable(self, exc: Exception) -> RuntimeError:
        return RuntimeError(
            f"Could not reach Ollama at {self.host}. "
            + START_HINT.format(model=self.model)
            + f" Details: {exc}"
        )

    @staticmethod
    def _tool_calls(message: dict[str, Any]) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for tc in message.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            arguments = fn.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"_raw": arguments}
            if not isinstance(arguments, dict):
                arguments = {"_raw": arguments}
            calls.append(
                ToolCall(id=uuid.uuid4().hex, name=fn.get("name", ""), arguments=arguments)
            )
        return calls

    def _record(
        self,
        body: dict[str, Any],
        messages: list[dict[str, Any]],
        content: str,
    ) -> None:
        prompt_tokens = int(body.get("prompt_eval_count") or 0) or sum(
            estimate_tokens(str(m.get("content") or "")) for m in messages
        )
        completion_tokens = int(body.get("eval_count") or 0) or estimate_tokens(content or "")
        self.budget.record(self.name, self.model, prompt_tokens, completion_tokens)

    # ------------------------------------------------------------------
    def chat(self, messages, tools=None) -> LLMResponse:
        payload = self._payload(messages, tools, stream=False)

        def attempt() -> requests.Response:
            resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp

        try:
            resp = call_with_retry(attempt, description=f"Ollama request to {self.model}")
        except requests.RequestException as exc:
            raise self._unreachable(exc) from exc

        body = resp.json()
        message = body.get("message", {}) or {}
        content = message.get("content") or None
        self._record(body, messages, content or "")
        return LLMResponse(
            content=content,
            tool_calls=self._tool_calls(message),
            provider=self.provider_name,
            empty=not content and not message.get("tool_calls"),
        )

    # ------------------------------------------------------------------
    def stream_response(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        sink: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Stream ``/api/chat`` line by line into ``sink``."""

        payload = self._payload(messages, tools, stream=True)
        if not payload.get("stream"):
            # Tools are in play: fall back to a single request.
            return super().stream_response(messages, tools, sink)

        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json=payload,
                timeout=self.timeout,
                stream=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise self._unreachable(exc) from exc

        parts: list[str] = []
        tool_calls: list[ToolCall] = []
        final: dict[str, Any] = {}
        with response:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:  # pragma: no cover - defensive
                    continue
                if chunk.get("error"):
                    raise RuntimeError(f"Ollama refused the request: {chunk['error']}")
                message = chunk.get("message", {}) or {}
                piece = message.get("content") or ""
                if piece:
                    parts.append(piece)
                    if sink is not None:
                        sink(piece)
                if message.get("tool_calls"):
                    tool_calls.extend(self._tool_calls(message))
                if chunk.get("done"):
                    final = chunk

        content = "".join(parts) or None
        self._record(final, messages, content or "")
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            provider=self.provider_name,
            empty=not content and not tool_calls,
        )

    # ------------------------------------------------------------------
    def list_models(self) -> list[str]:
        """Return the models pulled on this machine (empty when unreachable)."""

        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            resp.raise_for_status()
        except requests.RequestException:
            return []
        models = resp.json().get("models", []) or []
        return sorted(str(item.get("name", "")) for item in models if item.get("name"))

    def available(self) -> bool:
        """True when the server answers and the configured model is present."""

        models = self.list_models()
        if not models:
            return False
        wanted = self.model.split(":")[0]
        return any(name.split(":")[0] == wanted for name in models)
