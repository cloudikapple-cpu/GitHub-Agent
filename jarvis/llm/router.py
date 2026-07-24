"""Route requests across several providers.

The intended setup: a **local model** (Ollama, LM Studio, llama.cpp) handles
everyday work for free and offline, while a cloud endpoint such as **NVIDIA
NIM** takes over when the local model is unavailable, errors out, or the task
is heavy.

Example ``config.yaml``::

    router:
      enabled: true
      primary: ollama       # local
      fallbacks: [nim]      # cloud rescue
      heavy: nim            # long or explicitly hard requests
      escalate_over_chars: 4000
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, Callable

from .base import LLMBackend, LLMResponse

LOGGER = logging.getLogger(__name__)

#: Hints in the conversation that justify jumping straight to the heavy model.
HEAVY_HINTS = (
    "think hard",
    "deep dive",
    "подробно разбер",
    "сложн",
    "architecture review",
    "рефактор",
)


class RoutingBackend(LLMBackend):
    """Try providers in order until one answers."""

    name = "router"

    def __init__(
        self,
        factories: dict[str, Callable[[], LLMBackend]],
        primary: str,
        fallbacks: list[str] | None = None,
        heavy: str = "",
        escalate_over_chars: int = 4000,
    ) -> None:
        self._factories = factories
        self._cache: dict[str, LLMBackend] = {}
        self.primary = primary
        self.fallbacks = [name for name in (fallbacks or []) if name != primary]
        self.heavy = heavy
        self.escalate_over_chars = escalate_over_chars
        #: Provider that answered the most recent request.
        self.last_provider = ""

    # ------------------------------------------------------------------
    def backend(self, name: str) -> LLMBackend:
        """Instantiate (and cache) a backend by provider name."""

        if name not in self._cache:
            factory = self._factories.get(name)
            if factory is None:
                raise ValueError(f"Router refers to unknown provider '{name}'.")
            self._cache[name] = factory()
        return self._cache[name]

    # ------------------------------------------------------------------
    def is_heavy(self, messages: list[dict[str, Any]]) -> bool:
        """Decide whether the request deserves the strong model."""

        if not self.heavy or self.heavy == self.primary:
            return False
        text = "\n".join(str(m.get("content") or "") for m in messages)
        if len(text) > self.escalate_over_chars:
            return True
        last_user = next(
            (str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        ).lower()
        return any(hint in last_user for hint in HEAVY_HINTS)

    def order(self, messages: list[dict[str, Any]]) -> list[str]:
        """Provider names to try, in order."""

        chain = [self.heavy] if self.is_heavy(messages) else [self.primary]
        for name in [self.primary, *self.fallbacks, self.heavy]:
            if name and name not in chain:
                chain.append(name)
        return [name for name in chain if name in self._factories]

    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        errors: list[str] = []
        for name in self.order(messages):
            try:
                response = self.backend(name).chat(messages, tools)
            except Exception as exc:  # noqa: BLE001 - the point is to fall through
                LOGGER.warning("Provider '%s' failed: %s", name, exc)
                errors.append(f"{name}: {exc}")
                continue
            self.last_provider = name
            response.provider = name
            return response

        raise RuntimeError("All providers failed. " + "; ".join(errors))

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[str]:
        errors: list[str] = []
        for name in self.order(messages):
            try:
                backend = self.backend(name)
                chunks = backend.stream(messages, tools)
                first = next(chunks, None)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Provider '%s' failed while streaming: %s", name, exc)
                errors.append(f"{name}: {exc}")
                continue
            self.last_provider = name
            if first is not None:
                yield first
                yield from chunks
            return

        raise RuntimeError("All providers failed. " + "; ".join(errors))
