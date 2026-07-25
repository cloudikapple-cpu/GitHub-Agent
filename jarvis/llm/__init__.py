"""LLM backends and a factory driven by :class:`jarvis.config.Config`.

Three *kinds* of endpoint are supported:

* ``openai``    — any OpenAI-compatible Chat Completions API (custom base_url + headers);
* ``anthropic`` — the Anthropic Messages API;
* ``ollama``    — a local Ollama server.

You can also register your own backend class at runtime::

    from jarvis.llm import register_backend
    register_backend("my-api", MyBackend)

With ``router.enabled`` the factory returns a :class:`RoutingBackend` that
tries a local model first and falls back to a cloud endpoint (NVIDIA NIM by
default).
"""

from __future__ import annotations

from typing import Callable

from ..config import Config, ProviderConfig
from .base import LLMBackend, LLMResponse, ToolCall
from .router import RoutingBackend

__all__ = [
    "LLMBackend",
    "LLMResponse",
    "RoutingBackend",
    "ToolCall",
    "build_backend",
    "build_backend_from_provider",
    "build_router",
    "register_backend",
]

#: Custom backend factories keyed by provider *kind*.
_CUSTOM_BACKENDS: dict[str, Callable[[ProviderConfig], LLMBackend]] = {}


def register_backend(kind: str, factory: Callable[[ProviderConfig], LLMBackend]) -> None:
    """Register a factory for a custom provider kind."""

    _CUSTOM_BACKENDS[kind.lower()] = factory


def build_backend_from_provider(provider: ProviderConfig) -> LLMBackend:
    kind = (provider.kind or "openai").lower()

    if kind in _CUSTOM_BACKENDS:
        return _CUSTOM_BACKENDS[kind](provider)

    if kind in {"openai", "openai-compatible", "custom"}:
        from .openai_backend import OpenAIBackend

        return OpenAIBackend.from_provider(provider)

    if kind == "anthropic":
        from .anthropic_backend import AnthropicBackend

        return AnthropicBackend(
            api_key=provider.api_key,
            model=provider.model or "claude-3-5-sonnet-latest",
        )

    if kind == "ollama":
        from .ollama_backend import OllamaBackend

        return OllamaBackend(
            host=provider.base_url or "http://localhost:11434",
            model=provider.model or "llama3.1",
        )

    raise ValueError(
        f"Unknown provider kind '{provider.kind}'. Use openai, anthropic, ollama, "
        "or register your own with jarvis.llm.register_backend()."
    )


def build_router(config: Config) -> RoutingBackend:
    """Build a :class:`RoutingBackend` from ``config.router``."""

    factories: dict[str, Callable[[], LLMBackend]] = {}
    for name, provider in config.providers.items():
        factories[name] = (lambda p=provider: build_backend_from_provider(p))

    router = config.router
    primary = router.primary if router.primary in factories else config.backend
    return RoutingBackend(
        factories=factories,
        primary=primary,
        fallbacks=[name for name in router.fallbacks if name in factories],
        heavy=router.heavy if router.heavy in factories else "",
        escalate_over_chars=router.escalate_over_chars,
    )


def build_backend(config: Config, name: str | None = None) -> LLMBackend:
    """Instantiate the backend selected in ``config`` (or the named provider).

    When ``router.enabled`` is set and no explicit provider is requested, a
    routing backend with automatic fallback is returned instead.
    """

    if name is None and config.router.enabled:
        return build_router(config)
    return build_backend_from_provider(config.provider(name))
