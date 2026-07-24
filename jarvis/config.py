"""Configuration loading for Jarvis.

Resolved from three sources, in increasing priority:

1. Built-in defaults.
2. Environment variables (optionally loaded from a ``.env`` file).
3. A YAML file (``config.yaml`` by default).

Any OpenAI-compatible endpoint can be used as a provider — OpenRouter, Groq,
Together, DeepSeek, Mistral, LM Studio, vLLM, a corporate gateway, or your own
server — by setting ``base_url`` (and optional custom ``headers``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .security import (
    DEFAULT_DENIED_COMMAND_PATTERNS,
    DEFAULT_DENIED_PATH_PATTERNS,
    SecurityPolicy,
)

try:  # optional dependency
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False

try:  # optional dependency
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(item) for item in value]


def _expand(value: Any) -> Any:
    """Expand ``${ENV_VAR}`` references inside YAML strings."""

    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@dataclass
class ProviderConfig:
    """A single LLM endpoint."""

    name: str = "openai"
    #: How to talk to it: ``openai`` (any OpenAI-compatible API), ``anthropic`` or ``ollama``.
    kind: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    temperature: float | None = None
    max_tokens: int = 4096
    extra_body: dict[str, Any] = field(default_factory=dict)
    timeout: int = 180

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "ProviderConfig":
        data = _expand(data or {})
        return cls(
            name=name,
            kind=str(data.get("kind", "openai")).lower(),
            model=str(data.get("model", "")),
            api_key=str(data.get("api_key", "") or ""),
            base_url=str(data.get("base_url", "") or ""),
            headers={str(k): str(v) for k, v in (data.get("headers") or {}).items()},
            temperature=data.get("temperature"),
            max_tokens=int(data.get("max_tokens", 4096)),
            extra_body=dict(data.get("extra_body") or {}),
            timeout=int(data.get("timeout", 180)),
        )


@dataclass
class VoiceConfig:
    enabled: bool = False
    #: ``whisper`` (local, offline), ``google`` (SpeechRecognition), ``vosk``.
    stt: str = "whisper"
    whisper_model: str = "base"
    language: str = "ru"
    #: ``pyttsx3`` (offline) or ``none``.
    tts: str = "pyttsx3"
    speak_replies: bool = True
    record_seconds: float = 8.0


@dataclass
class InterfaceConfig:
    #: Global shortcut that opens the quick-ask window.
    hotkey: str = "ctrl+alt+space"
    #: Global shortcut that starts voice capture straight away.
    voice_hotkey: str = "ctrl+alt+v"
    overlay: bool = True
    notify: bool = True


@dataclass
class MemoryConfig:
    persist: bool = True
    path: str = "~/.jarvis/history.json"
    notes_path: str = "~/.jarvis/notes.md"
    max_messages: int = 60
    max_chars: int = 24000


@dataclass
class Config:
    """Runtime configuration for the assistant."""

    backend: str = "openai"
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    # behaviour
    require_confirmation: bool = True
    max_iterations: int = 12
    persona: str = ""

    # capabilities
    allow_shell: bool = True
    allow_exec: bool = True
    allow_desktop: bool = True
    allow_app_management: bool = False
    allow_network: bool = True

    # sandbox
    allowed_roots: list[str] = field(default_factory=list)
    denied_path_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_DENIED_PATH_PATTERNS)
    )
    denied_command_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_DENIED_COMMAND_PATTERNS)
    )
    audit_log: str = "~/.jarvis/audit.log"

    # subsystems
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    interface: InterfaceConfig = field(default_factory=InterfaceConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    skills_dirs: list[str] = field(
        default_factory=lambda: ["~/.jarvis/skills", "./skills"]
    )
    #: Named REST services the assistant can call, e.g. Notion, Home Assistant, Jira.
    integrations: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, config_path: str | os.PathLike[str] | None = "config.yaml") -> "Config":
        load_dotenv()
        cfg = cls()
        cfg._apply_env()
        if config_path and yaml is not None:
            path = Path(config_path).expanduser()
            if path.is_file():
                cfg._apply_yaml(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        cfg._ensure_builtin_providers()
        return cfg

    # ------------------------------------------------------------------
    def _apply_env(self) -> None:
        self.backend = os.getenv("JARVIS_BACKEND", self.backend)
        self.require_confirmation = _as_bool(
            os.getenv("JARVIS_REQUIRE_CONFIRMATION"), self.require_confirmation
        )
        self.max_iterations = int(os.getenv("JARVIS_MAX_ITERATIONS", self.max_iterations))
        self.persona = os.getenv("JARVIS_PERSONA", self.persona)

        self.allow_shell = _as_bool(os.getenv("JARVIS_ALLOW_SHELL"), self.allow_shell)
        self.allow_exec = _as_bool(os.getenv("JARVIS_ALLOW_EXEC"), self.allow_exec)
        self.allow_desktop = _as_bool(os.getenv("JARVIS_ALLOW_DESKTOP"), self.allow_desktop)
        self.allow_app_management = _as_bool(
            os.getenv("JARVIS_ALLOW_APP_MANAGEMENT"), self.allow_app_management
        )
        self.allow_network = _as_bool(os.getenv("JARVIS_ALLOW_NETWORK"), self.allow_network)

        if os.getenv("JARVIS_ALLOWED_ROOTS"):
            self.allowed_roots = _as_list(os.getenv("JARVIS_ALLOWED_ROOTS"))
        self.audit_log = os.getenv("JARVIS_AUDIT_LOG", self.audit_log)

        self.interface.hotkey = os.getenv("JARVIS_HOTKEY", self.interface.hotkey)
        self.interface.voice_hotkey = os.getenv(
            "JARVIS_VOICE_HOTKEY", self.interface.voice_hotkey
        )
        self.voice.enabled = _as_bool(os.getenv("JARVIS_VOICE"), self.voice.enabled)
        self.voice.language = os.getenv("JARVIS_VOICE_LANGUAGE", self.voice.language)

        if os.getenv("JARVIS_SKILLS_DIRS"):
            self.skills_dirs = _as_list(os.getenv("JARVIS_SKILLS_DIRS"))

        # Built-in providers configured through the classic variables.
        self.providers["openai"] = ProviderConfig(
            name="openai",
            kind="openai",
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", ""),
        )
        self.providers["anthropic"] = ProviderConfig(
            name="anthropic",
            kind="anthropic",
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            base_url=os.getenv("ANTHROPIC_BASE_URL", ""),
        )
        self.providers["ollama"] = ProviderConfig(
            name="ollama",
            kind="ollama",
            model=os.getenv("OLLAMA_MODEL", "llama3.1"),
            base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        )

        # A fully custom endpoint straight from the environment.
        if os.getenv("JARVIS_API_BASE") or os.getenv("JARVIS_MODEL"):
            self.providers["custom"] = ProviderConfig(
                name="custom",
                kind=os.getenv("JARVIS_API_KIND", "openai").lower(),
                model=os.getenv("JARVIS_MODEL", ""),
                api_key=os.getenv("JARVIS_API_KEY", ""),
                base_url=os.getenv("JARVIS_API_BASE", ""),
            )

    # ------------------------------------------------------------------
    def _apply_yaml(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        data = _expand(data)

        self.backend = data.get("backend", self.backend)

        for name, provider in (data.get("providers") or {}).items():
            self.providers[str(name)] = ProviderConfig.from_dict(str(name), provider)

        # Legacy top-level blocks stay supported.
        for legacy, kind in (("openai", "openai"), ("anthropic", "anthropic"), ("ollama", "ollama")):
            block = data.get(legacy)
            if not block:
                continue
            existing = self.providers.get(legacy) or ProviderConfig(name=legacy, kind=kind)
            existing.kind = kind
            existing.model = block.get("model", existing.model)
            existing.api_key = block.get("api_key", existing.api_key)
            existing.base_url = block.get("base_url", block.get("host", existing.base_url))
            self.providers[legacy] = existing

        behaviour = data.get("behaviour") or {}
        self.require_confirmation = _as_bool(
            behaviour.get("require_confirmation", self.require_confirmation),
            self.require_confirmation,
        )
        self.max_iterations = int(behaviour.get("max_iterations", self.max_iterations))
        self.persona = behaviour.get("persona", self.persona) or ""

        security = data.get("security") or {}
        self.allow_shell = _as_bool(security.get("allow_shell", behaviour.get("allow_shell", self.allow_shell)), self.allow_shell)
        self.allow_exec = _as_bool(security.get("allow_exec", self.allow_exec), self.allow_exec)
        self.allow_desktop = _as_bool(security.get("allow_desktop", self.allow_desktop), self.allow_desktop)
        self.allow_app_management = _as_bool(
            security.get("allow_app_management", self.allow_app_management),
            self.allow_app_management,
        )
        self.allow_network = _as_bool(security.get("allow_network", self.allow_network), self.allow_network)
        if security.get("allowed_roots") is not None:
            self.allowed_roots = _as_list(security.get("allowed_roots"))
        if security.get("denied_path_patterns") is not None:
            self.denied_path_patterns = _as_list(security.get("denied_path_patterns"))
        if security.get("denied_command_patterns") is not None:
            self.denied_command_patterns = _as_list(security.get("denied_command_patterns"))
        self.audit_log = security.get("audit_log", self.audit_log)

        voice = data.get("voice") or {}
        self.voice.enabled = _as_bool(voice.get("enabled", self.voice.enabled), self.voice.enabled)
        self.voice.stt = voice.get("stt", self.voice.stt)
        self.voice.whisper_model = voice.get("whisper_model", self.voice.whisper_model)
        self.voice.language = voice.get("language", self.voice.language)
        self.voice.tts = voice.get("tts", self.voice.tts)
        self.voice.speak_replies = _as_bool(
            voice.get("speak_replies", self.voice.speak_replies), self.voice.speak_replies
        )
        self.voice.record_seconds = float(voice.get("record_seconds", self.voice.record_seconds))

        interface = data.get("interface") or {}
        self.interface.hotkey = interface.get("hotkey", self.interface.hotkey)
        self.interface.voice_hotkey = interface.get("voice_hotkey", self.interface.voice_hotkey)
        self.interface.overlay = _as_bool(interface.get("overlay", self.interface.overlay), self.interface.overlay)
        self.interface.notify = _as_bool(interface.get("notify", self.interface.notify), self.interface.notify)

        memory = data.get("memory") or {}
        self.memory.persist = _as_bool(memory.get("persist", self.memory.persist), self.memory.persist)
        self.memory.path = memory.get("path", self.memory.path)
        self.memory.notes_path = memory.get("notes_path", self.memory.notes_path)
        self.memory.max_messages = int(memory.get("max_messages", self.memory.max_messages))
        self.memory.max_chars = int(memory.get("max_chars", self.memory.max_chars))

        if data.get("skills_dirs") is not None:
            self.skills_dirs = _as_list(data.get("skills_dirs"))
        if data.get("integrations"):
            self.integrations = {
                str(name): dict(spec or {})
                for name, spec in (data.get("integrations") or {}).items()
            }

    # ------------------------------------------------------------------
    def _ensure_builtin_providers(self) -> None:
        self.providers.setdefault("openai", ProviderConfig(name="openai", kind="openai"))
        self.providers.setdefault(
            "anthropic",
            ProviderConfig(name="anthropic", kind="anthropic", model="claude-3-5-sonnet-latest"),
        )
        self.providers.setdefault(
            "ollama",
            ProviderConfig(
                name="ollama", kind="ollama", model="llama3.1", base_url="http://localhost:11434"
            ),
        )

    # ------------------------------------------------------------------
    def provider(self, name: str | None = None) -> ProviderConfig:
        """Return the selected provider configuration."""

        key = (name or self.backend or "openai").lower()
        if key in self.providers:
            return self.providers[key]
        known = ", ".join(sorted(self.providers)) or "none"
        raise ValueError(f"Unknown backend '{key}'. Configured providers: {known}.")

    def policy(self) -> SecurityPolicy:
        """Build the :class:`SecurityPolicy` described by this config."""

        return SecurityPolicy(
            allowed_roots=list(self.allowed_roots),
            denied_path_patterns=list(self.denied_path_patterns),
            denied_command_patterns=list(self.denied_command_patterns),
            allow_shell=self.allow_shell,
            allow_exec=self.allow_exec,
            allow_desktop=self.allow_desktop,
            allow_app_management=self.allow_app_management,
            allow_network=self.allow_network,
            audit_log=self.audit_log,
        )

    # -- legacy accessors ------------------------------------------------
    @property
    def openai_api_key(self) -> str:
        return self.providers["openai"].api_key

    @property
    def openai_model(self) -> str:
        return self.providers["openai"].model

    @property
    def anthropic_api_key(self) -> str:
        return self.providers["anthropic"].api_key

    @property
    def anthropic_model(self) -> str:
        return self.providers["anthropic"].model

    @property
    def ollama_host(self) -> str:
        return self.providers["ollama"].base_url

    @property
    def ollama_model(self) -> str:
        return self.providers["ollama"].model
