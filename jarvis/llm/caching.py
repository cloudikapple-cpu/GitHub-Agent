"""A backend wrapper that remembers answers.

It sits in front of any other backend and is transparent: same interface, same
responses, minus the requests that were already paid for once.

Only plain answers are cached. A reply containing tool calls is passed through
untouched, because the value of that reply is the action it triggers, not the
text.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..cache import ResponseCache, fingerprint
from .base import LLMBackend, LLMResponse


class CachingBackend(LLMBackend):
    """Delegate to ``inner``, answering from ``cache`` when possible."""

    name = "cache"

    def __init__(self, inner: LLMBackend, cache: ResponseCache) -> None:
        self.inner = inner
        self.cache = cache

    # -- transparency ---------------------------------------------------
    @property
    def supports_vision(self) -> bool:  # type: ignore[override]
        return bool(getattr(self.inner, "supports_vision", False))

    @property
    def supports_streaming(self) -> bool:  # type: ignore[override]
        return bool(getattr(self.inner, "supports_streaming", False))

    @property
    def model(self) -> str:
        return str(getattr(self.inner, "model", "") or "")

    def __getattr__(self, item: str) -> Any:
        # Anything this wrapper does not define belongs to the real backend.
        return getattr(self.inner, item)

    # ------------------------------------------------------------------
    def _key(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> str:
        model = str(getattr(self.inner, "model", "") or getattr(self.inner, "name", ""))
        return fingerprint(model, messages, tools)

    def _remember(self, key: str, response: LLMResponse) -> None:
        if response.tool_calls or response.empty or response.cached:
            return
        if response.content:
            self.cache.set(key, response.content, self.model)

    def _replay(self, hit: str) -> LLMResponse:
        return LLMResponse(
            content=hit,
            provider=str(getattr(self.inner, "provider_name", "") or self.inner.name),
            cached=True,
        )

    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        key = self._key(messages, tools)
        hit = self.cache.get(key)
        if hit is not None:
            return self._replay(hit)
        response = self.inner.chat(messages, tools)
        self._remember(key, response)
        return response

    def stream_response(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        sink: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        key = self._key(messages, tools)
        hit = self.cache.get(key)
        if hit is not None:
            if sink is not None:
                sink(hit)
            return self._replay(hit)
        response = self.inner.stream_response(messages, tools, sink)
        self._remember(key, response)
        return response
