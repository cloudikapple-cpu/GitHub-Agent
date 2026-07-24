"""Configuration loading for Jarvis.

Configuration is resolved from three sources, in increasing priority:

1. Built-in defaults.
2. Environment variables (optionally loaded from a ``.env`` file).
3. A ``config.yaml`` file in the working directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # optional dependency
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False

try:  # optional dependency
    import yaml
except ImportError:  # pragma: no cover - PyYAML is optional
    yaml = None


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Config:
    """Runtime configuration for the assistant."""

    backend: str = "openai"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-latest"

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    allow_shell: bool = True
    require_confirmation: bool = True
    max_iterations: int = 12
    persona: str = ""

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, config_path: str | os.PathLike[str] | None = "config.yaml") -> "Config":
        """Build a :class:`Config` from env vars and an optional YAML file."""

        load_dotenv()
        cfg = cls(
            backend=os.getenv("JARVIS_BACKEND", "openai"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1"),
            allow_shell=_as_bool(os.getenv("JARVIS_ALLOW_SHELL"), True),
            require_confirmation=_as_bool(os.getenv("JARVIS_REQUIRE_CONFIRMATION"), True),
            max_iterations=int(os.getenv("JARVIS_MAX_ITERATIONS", "12")),
        )

        if config_path and yaml is not None:
            path = Path(config_path)
            if path.is_file():
                cfg._apply_yaml(yaml.safe_load(path.read_text()) or {})

        return cfg

    # ------------------------------------------------------------------
    def _apply_yaml(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return

        self.backend = data.get("backend", self.backend)

        openai = data.get("openai") or {}
        self.openai_model = openai.get("model", self.openai_model)
        self.openai_api_key = openai.get("api_key", self.openai_api_key)

        anthropic = data.get("anthropic") or {}
        self.anthropic_model = anthropic.get("model", self.anthropic_model)
        self.anthropic_api_key = anthropic.get("api_key", self.anthropic_api_key)

        ollama = data.get("ollama") or {}
        self.ollama_host = ollama.get("host", self.ollama_host)
        self.ollama_model = ollama.get("model", self.ollama_model)

        behaviour = data.get("behaviour") or {}
        self.allow_shell = _as_bool(behaviour.get("allow_shell", self.allow_shell), self.allow_shell)
        self.require_confirmation = _as_bool(
            behaviour.get("require_confirmation", self.require_confirmation),
            self.require_confirmation,
        )
        self.max_iterations = int(behaviour.get("max_iterations", self.max_iterations))
        self.persona = behaviour.get("persona", self.persona) or ""
