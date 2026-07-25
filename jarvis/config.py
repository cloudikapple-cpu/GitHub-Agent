"""Configuration loading for Jarvis.

Resolved from three sources, in increasing priority:

1. Built-in defaults.
2. A YAML file (``config.yaml`` by default).
3. Environment variables (optionally loaded from a ``.env`` file).

Command-line flags are applied on top of all three by :mod:`jarvis.cli`, so the
rule is: the closer a setting is to the command you just typed, the stronger it
is. Until 0.5.1 the YAML file was applied *after* the environment, so a stale
``config.yaml`` silently won over ``.env`` — including the choice of provider.
Every value now records where it came from (:meth:`Config.source_of`), and
``jarvis --doctor`` prints it.

Any OpenAI-compatible endpoint can be used as a provider — OpenRouter, Groq,
NVIDIA NIM, Together, DeepSeek, LM Studio, vLLM, a corporate gateway, or your
own server — by setting ``base_url`` (and optional custom ``headers``).
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

#: Default endpoint for NVIDIA NIM (OpenAI-compatible).
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
NIM_DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"

#: Where a setting came from, reported by ``jarvis --doctor``.
SOURCE_DEFAULT = "default"
SOURCE_YAML = "config file"
SOURCE_ENV = "environment"
SOURCE_CLI = "command line"

#: Values accepted for the sandbox switch, which is a mode and not a flag.
_SANDBOX_MODES = ("none", "docker", "firejail")
_SANDBOX_OFF = {"", "0", "false", "no", "off"}
_SANDBOX_ON = {"1", "true", "yes", "on"}

#: Provider fields that can be set straight from the environment.
#: Kept at module level: an annotated dict inside the dataclass would be read
#: as a field with a mutable default.
_ENV_PROVIDER_FIELDS = {
    "openai": {
        "model": ("OPENAI_MODEL",),
        "api_key": ("OPENAI_API_KEY",),
        "base_url": ("OPENAI_BASE_URL",),
    },
    "anthropic": {
        "model": ("ANTHROPIC_MODEL",),
        "api_key": ("ANTHROPIC_API_KEY",),
        "base_url": ("ANTHROPIC_BASE_URL",),
    },
    "ollama": {
        "model": ("OLLAMA_MODEL",),
        "base_url": ("OLLAMA_HOST",),
    },
    "nim": {
        "model": ("NVIDIA_MODEL",),
        "api_key": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY"),
        "base_url": ("NVIDIA_BASE_URL",),
    },
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any, default: int) -> int:
    """Parse an integer, falling back to ``default`` instead of raising.

    A typo in ``.env`` used to end the run with a ``ValueError`` traceback
    before anything was constructed, which is a poor way to say 'this line is
    not a number'.
    """

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


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
    #: Set to true for models that can read images.
    vision: bool = False

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> ProviderConfig:
        data = _expand(data or {})
        return cls(
            name=name,
            kind=str(data.get("kind", "openai")).lower(),
            model=str(data.get("model", "")),
            api_key=str(data.get("api_key", "") or ""),
            base_url=str(data.get("base_url", "") or ""),
            headers={str(k): str(v) for k, v in (data.get("headers") or {}).items()},
            temperature=data.get("temperature"),
            max_tokens=_as_int(data.get("max_tokens", 4096), 4096),
            extra_body=dict(data.get("extra_body") or {}),
            timeout=_as_int(data.get("timeout", 180), 180),
            vision=_as_bool(data.get("vision"), False),
        )


@dataclass
class RouterConfig:
    """Route requests across several providers.

    The classic setup is a local model for everyday work with a cloud endpoint
    (NVIDIA NIM, OpenAI, ...) as the fallback for hard requests and outages.
    """

    enabled: bool = False
    #: Provider used first — typically a local Ollama/LM Studio model.
    primary: str = "ollama"
    #: Providers tried in order when the primary fails.
    fallbacks: list[str] = field(default_factory=lambda: ["nim"])
    #: Provider used when the request is marked as hard.
    heavy: str = "nim"
    #: Provider used for image understanding.
    vision: str = ""
    #: Escalate to `heavy` when the request is longer than this many characters.
    escalate_over_chars: int = 4000


@dataclass
class SearchConfig:
    """Web search settings. Tavily is an LLM-oriented search API."""

    #: ``tavily``, ``duckduckgo`` or ``auto`` (Tavily when a key is present).
    provider: str = "auto"
    tavily_api_key: str = ""
    max_results: int = 5
    #: Tavily only: ``basic`` or ``advanced``.
    depth: str = "basic"
    #: Tavily only: ask for a short synthesised answer alongside the results.
    include_answer: bool = True


@dataclass
class KnowledgeConfig:
    """Long-term semantic memory."""

    enabled: bool = True
    path: str = "~/.jarvis/knowledge.db"
    #: Provider name used for embeddings; empty means the offline hashing fallback.
    embedding_provider: str = ""
    embedding_model: str = "text-embedding-3-small"
    top_k: int = 5
    #: Automatically store a summary of each session.
    autosave_sessions: bool = True


@dataclass
class SchedulerConfig:
    """Reminders and scheduled tasks."""

    enabled: bool = True
    path: str = "~/.jarvis/jobs.json"
    #: How often the scheduler wakes up, in seconds.
    tick_seconds: int = 20
    #: Watch folders and fire jobs on file changes.
    watch_paths: list[str] = field(default_factory=list)


@dataclass
class SandboxConfig:
    """Isolated execution for shell commands and code."""

    #: ``none``, ``docker`` or ``firejail``.
    mode: str = "none"
    image: str = "python:3.12-slim"
    #: Allow network access inside the sandbox.
    network: bool = False
    #: Host folder mounted as the working directory.
    workdir: str = "~/.jarvis/sandbox"
    timeout: int = 120
    memory_limit: str = "1g"


@dataclass
class VisionConfig:
    """Screenshot understanding."""

    enabled: bool = False
    #: Provider name with a vision-capable model; empty means the active one.
    provider: str = ""
    max_width: int = 1280


@dataclass
class TelegramConfig:
    """Control Jarvis from your phone."""

    enabled: bool = False
    token: str = ""
    #: Only these Telegram user ids may talk to the bot. Empty = nobody.
    allowed_user_ids: list[str] = field(default_factory=list)
    #: Confirmations are impossible over chat, so risky tools are refused by default.
    allow_confirmations: bool = False


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
    #: Show a system tray icon when running as a daemon.
    tray: bool = True
    #: Stream the reply token by token where the interface supports it.
    stream: bool = True


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
    #: Plan only: describe the actions instead of running them.
    dry_run: bool = False

    # capabilities
    allow_shell: bool = True
    allow_exec: bool = True
    allow_desktop: bool = True
    allow_app_management: bool = False
    allow_network: bool = True

    # sandbox (filesystem/commands)
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
    router: RouterConfig = field(default_factory=RouterConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    execution_sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)

    skills_dirs: list[str] = field(
        default_factory=lambda: ["~/.jarvis/skills", "./skills"]
    )
    #: Named REST services the assistant can call, e.g. Notion, Home Assistant, Jira.
    integrations: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: MCP servers: {name: {command, args, env}} for stdio or {name: {url}} for HTTP.
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)

    # provenance
    #: The YAML file that was actually read, empty when there was none.
    config_file: str = ""
    #: Where each setting came from: see the ``SOURCE_*`` constants.
    sources: dict[str, str] = field(default_factory=dict)
    #: Human-readable notes about settings that were overridden along the way.
    overrides: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, config_path: str | os.PathLike[str] | None = "config.yaml") -> Config:
        """Build the configuration from defaults, the YAML file and the environment.

        The order matters and it is the opposite of what it was before 0.5.1:
        the environment is applied *last*, so `.env` beats a forgotten
        ``config.yaml``.
        """

        load_dotenv()
        cfg = cls()
        cfg._ensure_builtin_providers()
        if config_path and yaml is not None:
            path = Path(config_path).expanduser()
            if path.is_file():
                cfg.config_file = str(path)
                cfg._apply_yaml(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        cfg._apply_env()
        cfg._ensure_builtin_providers()
        return cfg

    # -- provenance ------------------------------------------------------
    def mark_source(self, key: str, source: str) -> None:
        """Record where ``key`` was last set, and note any override."""

        previous = self.sources.get(key)
        if previous and previous != source:
            note = f"{key}: {source} overrides {previous}"
            if note not in self.overrides:
                self.overrides.append(note)
        self.sources[key] = source

    def source_of(self, key: str) -> str:
        """Return the raw source name for ``key`` (``default`` when untouched)."""

        return self.sources.get(key, SOURCE_DEFAULT)

    def describe_source(self, key: str) -> str:
        """Return the source of ``key`` with the file name when it is a file."""

        source = self.source_of(key)
        if source == SOURCE_YAML and self.config_file:
            return f"{SOURCE_YAML} {self.config_file}"
        return source

    # ------------------------------------------------------------------
    def _env_str(self, name: str, current: str, key: str = "") -> str:
        value = os.getenv(name)
        if value is None:
            return current
        if key:
            self.mark_source(key, SOURCE_ENV)
        return value

    def _env_bool(self, name: str, current: bool, key: str = "") -> bool:
        value = os.getenv(name)
        if value is None or value == "":
            return current
        if key:
            self.mark_source(key, SOURCE_ENV)
        return _as_bool(value, current)

    def _env_int(self, name: str, current: int, key: str = "") -> int:
        value = os.getenv(name)
        if value is None:
            return current
        if key:
            self.mark_source(key, SOURCE_ENV)
        return _as_int(value, current)

    def _env_list(self, name: str, current: list[str], key: str = "") -> list[str]:
        value = os.getenv(name)
        if not value:
            return current
        if key:
            self.mark_source(key, SOURCE_ENV)
        return _as_list(value)

    # ------------------------------------------------------------------
    def _apply_env_providers(self) -> None:
        """Apply the classic per-provider variables, if they are set.

        Only variables that actually exist are applied, so a provider block in
        ``config.yaml`` keeps every field the environment says nothing about.
        """

        for provider_name, fields in _ENV_PROVIDER_FIELDS.items():
            provider = self.providers.get(provider_name)
            if provider is None:
                continue
            for attribute, variables in fields.items():
                for variable in variables:
                    value = os.getenv(variable)
                    if value:
                        setattr(provider, attribute, value)
                        self.mark_source(
                            f"providers.{provider_name}.{attribute}", SOURCE_ENV
                        )
                        break

        # A fully custom endpoint straight from the environment.
        if os.getenv("JARVIS_API_BASE") or os.getenv("JARVIS_MODEL"):
            custom = self.providers.get("custom") or ProviderConfig(
                name="custom", kind="openai", model=""
            )
            custom.kind = os.getenv("JARVIS_API_KIND", custom.kind).lower()
            custom.model = os.getenv("JARVIS_MODEL", custom.model)
            custom.api_key = os.getenv("JARVIS_API_KEY", custom.api_key)
            custom.base_url = os.getenv("JARVIS_API_BASE", custom.base_url)
            self.providers["custom"] = custom
            self.mark_source("providers.custom", SOURCE_ENV)

    def _apply_env_sandbox(self) -> None:
        """Read ``JARVIS_SANDBOX``, which is a mode but is often written as a flag."""

        value = os.getenv("JARVIS_SANDBOX")
        if value is None:
            return
        mode = value.strip().lower()
        if mode in _SANDBOX_OFF:
            mode = "none"
        elif mode in _SANDBOX_ON:
            mode = "docker"
        if mode in _SANDBOX_MODES:
            self.execution_sandbox.mode = mode
            self.mark_source("execution_sandbox.mode", SOURCE_ENV)

    # ------------------------------------------------------------------
    def _apply_env(self) -> None:
        self.backend = self._env_str("JARVIS_BACKEND", self.backend, "backend")
        self.require_confirmation = self._env_bool(
            "JARVIS_REQUIRE_CONFIRMATION", self.require_confirmation, "require_confirmation"
        )
        self.max_iterations = self._env_int(
            "JARVIS_MAX_ITERATIONS", self.max_iterations, "max_iterations"
        )
        self.persona = self._env_str("JARVIS_PERSONA", self.persona, "persona")
        self.dry_run = self._env_bool("JARVIS_DRY_RUN", self.dry_run, "dry_run")

        self.allow_shell = self._env_bool("JARVIS_ALLOW_SHELL", self.allow_shell, "allow_shell")
        self.allow_exec = self._env_bool("JARVIS_ALLOW_EXEC", self.allow_exec, "allow_exec")
        self.allow_desktop = self._env_bool(
            "JARVIS_ALLOW_DESKTOP", self.allow_desktop, "allow_desktop"
        )
        self.allow_app_management = self._env_bool(
            "JARVIS_ALLOW_APP_MANAGEMENT", self.allow_app_management, "allow_app_management"
        )
        self.allow_network = self._env_bool(
            "JARVIS_ALLOW_NETWORK", self.allow_network, "allow_network"
        )

        self.allowed_roots = self._env_list(
            "JARVIS_ALLOWED_ROOTS", self.allowed_roots, "allowed_roots"
        )
        self.audit_log = self._env_str("JARVIS_AUDIT_LOG", self.audit_log, "audit_log")

        self.interface.hotkey = self._env_str(
            "JARVIS_HOTKEY", self.interface.hotkey, "interface.hotkey"
        )
        self.interface.voice_hotkey = self._env_str(
            "JARVIS_VOICE_HOTKEY", self.interface.voice_hotkey, "interface.voice_hotkey"
        )
        self.interface.stream = self._env_bool(
            "JARVIS_STREAM", self.interface.stream, "interface.stream"
        )
        self.interface.tray = self._env_bool(
            "JARVIS_TRAY", self.interface.tray, "interface.tray"
        )
        self.voice.enabled = self._env_bool("JARVIS_VOICE", self.voice.enabled, "voice.enabled")
        self.voice.language = self._env_str(
            "JARVIS_VOICE_LANGUAGE", self.voice.language, "voice.language"
        )

        self.skills_dirs = self._env_list(
            "JARVIS_SKILLS_DIRS", self.skills_dirs, "skills_dirs"
        )

        # -- search --
        self.search.tavily_api_key = self._env_str(
            "TAVILY_API_KEY", self.search.tavily_api_key, "search.tavily_api_key"
        )
        self.search.provider = self._env_str(
            "JARVIS_SEARCH_PROVIDER", self.search.provider, "search.provider"
        )

        # -- router --
        self.router.enabled = self._env_bool(
            "JARVIS_ROUTER", self.router.enabled, "router.enabled"
        )
        self.router.primary = self._env_str(
            "JARVIS_ROUTER_PRIMARY", self.router.primary, "router.primary"
        )
        self.router.heavy = self._env_str(
            "JARVIS_ROUTER_HEAVY", self.router.heavy, "router.heavy"
        )
        self.router.fallbacks = self._env_list(
            "JARVIS_ROUTER_FALLBACKS", self.router.fallbacks, "router.fallbacks"
        )

        # -- execution sandbox --
        self._apply_env_sandbox()
        self.execution_sandbox.image = self._env_str(
            "JARVIS_SANDBOX_IMAGE", self.execution_sandbox.image, "execution_sandbox.image"
        )

        # -- knowledge & scheduler --
        self.knowledge.enabled = self._env_bool(
            "JARVIS_KNOWLEDGE", self.knowledge.enabled, "knowledge.enabled"
        )
        self.scheduler.enabled = self._env_bool(
            "JARVIS_SCHEDULER", self.scheduler.enabled, "scheduler.enabled"
        )

        # -- telegram --
        self.telegram.token = self._env_str(
            "TELEGRAM_BOT_TOKEN", self.telegram.token, "telegram.token"
        )
        self.telegram.allowed_user_ids = self._env_list(
            "TELEGRAM_ALLOWED_USERS", self.telegram.allowed_user_ids, "telegram.allowed_user_ids"
        )
        self.telegram.enabled = self._env_bool(
            "JARVIS_TELEGRAM", self.telegram.enabled, "telegram.enabled"
        )

        self._apply_env_providers()

    # ------------------------------------------------------------------
    def _merge_provider(self, name: str, data: Any) -> None:
        """Apply a YAML provider block on top of what is already configured.

        Fields the block does not mention keep their built-in value, so a two
        line ``nim:`` block no longer erases the default endpoint.
        """

        block = dict(data or {})
        parsed = ProviderConfig.from_dict(name, block)
        existing = self.providers.get(name)
        if existing is None:
            self.providers[name] = parsed
        else:
            for attribute in (
                "kind",
                "model",
                "api_key",
                "base_url",
                "headers",
                "temperature",
                "max_tokens",
                "extra_body",
                "timeout",
                "vision",
            ):
                if attribute in block:
                    setattr(existing, attribute, getattr(parsed, attribute))
        for attribute in block:
            self.mark_source(f"providers.{name}.{attribute}", SOURCE_YAML)

    # ------------------------------------------------------------------
    def _apply_yaml(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        data = _expand(data)

        if data.get("backend"):
            self.backend = str(data["backend"])
            self.mark_source("backend", SOURCE_YAML)

        for name, provider in (data.get("providers") or {}).items():
            self._merge_provider(str(name), provider)

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
            self.mark_source(f"providers.{legacy}.model", SOURCE_YAML)

        behaviour = data.get("behaviour") or {}
        self.require_confirmation = _as_bool(
            behaviour.get("require_confirmation", self.require_confirmation),
            self.require_confirmation,
        )
        if "require_confirmation" in behaviour:
            self.mark_source("require_confirmation", SOURCE_YAML)
        self.max_iterations = _as_int(
            behaviour.get("max_iterations", self.max_iterations), self.max_iterations
        )
        if "max_iterations" in behaviour:
            self.mark_source("max_iterations", SOURCE_YAML)
        self.persona = behaviour.get("persona", self.persona) or ""
        self.dry_run = _as_bool(behaviour.get("dry_run", self.dry_run), self.dry_run)

        security = data.get("security") or {}
        self.allow_shell = _as_bool(
            security.get("allow_shell", behaviour.get("allow_shell", self.allow_shell)),
            self.allow_shell,
        )
        self.allow_exec = _as_bool(security.get("allow_exec", self.allow_exec), self.allow_exec)
        self.allow_desktop = _as_bool(
            security.get("allow_desktop", self.allow_desktop), self.allow_desktop
        )
        self.allow_app_management = _as_bool(
            security.get("allow_app_management", self.allow_app_management),
            self.allow_app_management,
        )
        self.allow_network = _as_bool(
            security.get("allow_network", self.allow_network), self.allow_network
        )
        for switch in (
            "allow_shell",
            "allow_exec",
            "allow_desktop",
            "allow_app_management",
            "allow_network",
        ):
            if switch in security:
                self.mark_source(switch, SOURCE_YAML)
        if security.get("allowed_roots") is not None:
            self.allowed_roots = _as_list(security.get("allowed_roots"))
            self.mark_source("allowed_roots", SOURCE_YAML)
        if security.get("denied_path_patterns") is not None:
            self.denied_path_patterns = _as_list(security.get("denied_path_patterns"))
        if security.get("denied_command_patterns") is not None:
            self.denied_command_patterns = _as_list(security.get("denied_command_patterns"))
        self.audit_log = security.get("audit_log", self.audit_log)

        sandbox = data.get("execution_sandbox") or security.get("execution_sandbox") or {}
        self.execution_sandbox.mode = sandbox.get("mode", self.execution_sandbox.mode)
        if "mode" in sandbox:
            self.mark_source("execution_sandbox.mode", SOURCE_YAML)
        self.execution_sandbox.image = sandbox.get("image", self.execution_sandbox.image)
        self.execution_sandbox.network = _as_bool(
            sandbox.get("network", self.execution_sandbox.network), self.execution_sandbox.network
        )
        self.execution_sandbox.workdir = sandbox.get("workdir", self.execution_sandbox.workdir)
        self.execution_sandbox.timeout = _as_int(
            sandbox.get("timeout", self.execution_sandbox.timeout), self.execution_sandbox.timeout
        )
        self.execution_sandbox.memory_limit = sandbox.get(
            "memory_limit", self.execution_sandbox.memory_limit
        )

        voice = data.get("voice") or {}
        self.voice.enabled = _as_bool(voice.get("enabled", self.voice.enabled), self.voice.enabled)
        if "enabled" in voice:
            self.mark_source("voice.enabled", SOURCE_YAML)
        self.voice.stt = voice.get("stt", self.voice.stt)
        self.voice.whisper_model = voice.get("whisper_model", self.voice.whisper_model)
        self.voice.language = voice.get("language", self.voice.language)
        if "language" in voice:
            self.mark_source("voice.language", SOURCE_YAML)
        self.voice.tts = voice.get("tts", self.voice.tts)
        self.voice.speak_replies = _as_bool(
            voice.get("speak_replies", self.voice.speak_replies), self.voice.speak_replies
        )
        self.voice.record_seconds = _as_float(
            voice.get("record_seconds", self.voice.record_seconds), self.voice.record_seconds
        )

        interface = data.get("interface") or {}
        self.interface.hotkey = interface.get("hotkey", self.interface.hotkey)
        if "hotkey" in interface:
            self.mark_source("interface.hotkey", SOURCE_YAML)
        self.interface.voice_hotkey = interface.get("voice_hotkey", self.interface.voice_hotkey)
        if "voice_hotkey" in interface:
            self.mark_source("interface.voice_hotkey", SOURCE_YAML)
        self.interface.overlay = _as_bool(
            interface.get("overlay", self.interface.overlay), self.interface.overlay
        )
        self.interface.notify = _as_bool(
            interface.get("notify", self.interface.notify), self.interface.notify
        )
        self.interface.tray = _as_bool(
            interface.get("tray", self.interface.tray), self.interface.tray
        )
        if "tray" in interface:
            self.mark_source("interface.tray", SOURCE_YAML)
        self.interface.stream = _as_bool(
            interface.get("stream", self.interface.stream), self.interface.stream
        )
        if "stream" in interface:
            self.mark_source("interface.stream", SOURCE_YAML)

        memory = data.get("memory") or {}
        self.memory.persist = _as_bool(
            memory.get("persist", self.memory.persist), self.memory.persist
        )
        self.memory.path = memory.get("path", self.memory.path)
        self.memory.notes_path = memory.get("notes_path", self.memory.notes_path)
        self.memory.max_messages = _as_int(
            memory.get("max_messages", self.memory.max_messages), self.memory.max_messages
        )
        self.memory.max_chars = _as_int(
            memory.get("max_chars", self.memory.max_chars), self.memory.max_chars
        )

        router = data.get("router") or {}
        self.router.enabled = _as_bool(
            router.get("enabled", self.router.enabled), self.router.enabled
        )
        if "enabled" in router:
            self.mark_source("router.enabled", SOURCE_YAML)
        self.router.primary = router.get("primary", self.router.primary)
        if "primary" in router:
            self.mark_source("router.primary", SOURCE_YAML)
        self.router.heavy = router.get("heavy", self.router.heavy)
        if "heavy" in router:
            self.mark_source("router.heavy", SOURCE_YAML)
        self.router.vision = router.get("vision", self.router.vision)
        if router.get("fallbacks") is not None:
            self.router.fallbacks = _as_list(router.get("fallbacks"))
            self.mark_source("router.fallbacks", SOURCE_YAML)
        self.router.escalate_over_chars = _as_int(
            router.get("escalate_over_chars", self.router.escalate_over_chars),
            self.router.escalate_over_chars,
        )

        search = data.get("search") or {}
        self.search.provider = search.get("provider", self.search.provider)
        if "provider" in search:
            self.mark_source("search.provider", SOURCE_YAML)
        self.search.tavily_api_key = search.get("tavily_api_key", self.search.tavily_api_key)
        if "tavily_api_key" in search:
            self.mark_source("search.tavily_api_key", SOURCE_YAML)
        self.search.max_results = _as_int(
            search.get("max_results", self.search.max_results), self.search.max_results
        )
        self.search.depth = search.get("depth", self.search.depth)
        self.search.include_answer = _as_bool(
            search.get("include_answer", self.search.include_answer), self.search.include_answer
        )

        knowledge = data.get("knowledge") or {}
        self.knowledge.enabled = _as_bool(
            knowledge.get("enabled", self.knowledge.enabled), self.knowledge.enabled
        )
        if "enabled" in knowledge:
            self.mark_source("knowledge.enabled", SOURCE_YAML)
        self.knowledge.path = knowledge.get("path", self.knowledge.path)
        self.knowledge.embedding_provider = knowledge.get(
            "embedding_provider", self.knowledge.embedding_provider
        )
        self.knowledge.embedding_model = knowledge.get(
            "embedding_model", self.knowledge.embedding_model
        )
        self.knowledge.top_k = _as_int(
            knowledge.get("top_k", self.knowledge.top_k), self.knowledge.top_k
        )
        self.knowledge.autosave_sessions = _as_bool(
            knowledge.get("autosave_sessions", self.knowledge.autosave_sessions),
            self.knowledge.autosave_sessions,
        )

        scheduler = data.get("scheduler") or {}
        self.scheduler.enabled = _as_bool(
            scheduler.get("enabled", self.scheduler.enabled), self.scheduler.enabled
        )
        if "enabled" in scheduler:
            self.mark_source("scheduler.enabled", SOURCE_YAML)
        self.scheduler.path = scheduler.get("path", self.scheduler.path)
        self.scheduler.tick_seconds = _as_int(
            scheduler.get("tick_seconds", self.scheduler.tick_seconds), self.scheduler.tick_seconds
        )
        if scheduler.get("watch_paths") is not None:
            self.scheduler.watch_paths = _as_list(scheduler.get("watch_paths"))

        vision = data.get("vision") or {}
        self.vision.enabled = _as_bool(
            vision.get("enabled", self.vision.enabled), self.vision.enabled
        )
        self.vision.provider = vision.get("provider", self.vision.provider)
        self.vision.max_width = _as_int(
            vision.get("max_width", self.vision.max_width), self.vision.max_width
        )

        telegram = data.get("telegram") or {}
        self.telegram.enabled = _as_bool(
            telegram.get("enabled", self.telegram.enabled), self.telegram.enabled
        )
        if "enabled" in telegram:
            self.mark_source("telegram.enabled", SOURCE_YAML)
        self.telegram.token = telegram.get("token", self.telegram.token)
        if "token" in telegram:
            self.mark_source("telegram.token", SOURCE_YAML)
        if telegram.get("allowed_user_ids") is not None:
            self.telegram.allowed_user_ids = _as_list(telegram.get("allowed_user_ids"))
            self.mark_source("telegram.allowed_user_ids", SOURCE_YAML)
        self.telegram.allow_confirmations = _as_bool(
            telegram.get("allow_confirmations", self.telegram.allow_confirmations),
            self.telegram.allow_confirmations,
        )

        if data.get("skills_dirs") is not None:
            self.skills_dirs = _as_list(data.get("skills_dirs"))
            self.mark_source("skills_dirs", SOURCE_YAML)
        if data.get("integrations"):
            self.integrations = {
                str(name): dict(spec or {})
                for name, spec in (data.get("integrations") or {}).items()
            }
        if data.get("mcp_servers"):
            self.mcp_servers = {
                str(name): dict(spec or {})
                for name, spec in (data.get("mcp_servers") or {}).items()
            }

    # ------------------------------------------------------------------
    def _ensure_builtin_providers(self) -> None:
        self.providers.setdefault(
            "openai",
            ProviderConfig(name="openai", kind="openai", model="gpt-4o-mini", vision=True),
        )
        self.providers.setdefault(
            "anthropic",
            ProviderConfig(
                name="anthropic",
                kind="anthropic",
                model="claude-3-5-sonnet-latest",
                vision=True,
            ),
        )
        self.providers.setdefault(
            "ollama",
            ProviderConfig(
                name="ollama", kind="ollama", model="llama3.1", base_url="http://localhost:11434"
            ),
        )
        self.providers.setdefault(
            "nim",
            ProviderConfig(
                name="nim", kind="openai", model=NIM_DEFAULT_MODEL, base_url=NIM_BASE_URL
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
