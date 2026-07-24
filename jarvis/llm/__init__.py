"""LLM backends and a factory to build one from :class:`jarvis.config.Config`."""

from __future__ import annotations

from ..config import Config
from .base import LLMBackend, LLMResponse, ToolCall

__all__ = ["LLMBackend", "LLMResponse", "ToolCall", "build_backend"]


def build_backend(config: Config) -> LLMBackend:
    """Instantiate the backend selected in ``config``."""

    backend = (config.backend or "openai").lower()

    if backend == "openai":
        from .openai_backend import OpenAIBackend

        return OpenAIBackend(api_key=config.openai_api_key, model=config.openai_model)

    if backend == "anthropic":
        from .anthropic_backend import AnthropicBackend

        return AnthropicBackend(api_key=config.anthropic_api_key, model=config.anthropic_model)

    if backend == "ollama":
        from .ollama_backend import OllamaBackend

        return OllamaBackend(host=config.ollama_host, model=config.ollama_model)

    raise ValueError(f"Unknown backend '{config.backend}'. Use one of: openai, anthropic, ollama.")
