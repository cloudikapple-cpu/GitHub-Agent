"""Configuration loading for Jarvis.

Resolved from three sources, in increasing priority:

1. Built-in defaults.
2. Environment variables (optionally loaded from a ``.env`` file).
3. A YAML file (``config.yaml`` by default).

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
    #: Set to true for models that can read images.
    vision: bool = False

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
        self.dry_run = _as_bool(os.getenv("JARVIS_DRY_RUN"), self.dry_run)

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

        # -- search --
        self.search.tavily_api_key = os.getenv("TAVILY_API_KEY", self.search.tavily_api_key)
        self.search.provider = os.getenv("JARVIS_SEARCH_PROVIDER", self.search.provider)

        # -- router --
        self.router.enabled = _as_bool(os.getenv("JARVIS_ROUTER"), self.router.enabled)
        self.router.primary = os.getenv("JARVIS_ROUTER_PRIMARY", self.router.primary)
        self.router.heavy = os.getenv("JARVIS_ROUTER_HEAVY", self.router.heavy)
        if os.getenv("JARVIS_ROUTER_FALLBACKS"):
            self.router.fallbacks = _as_list(os.getenv("JARVIS_ROUTER_FALLBACKS"))

        # -- execution sandbox --
        self.execution_sandbox.mode = os.getenv("JARVIS_SANDBOX", self.execution_sandbox.mode)
        self.execution_sandbox.image = os.getenv(
            "JARVIS_SANDBOX_IMAGE", self.execution_sandbox.image
        )

        # -- knowledge & scheduler --
        self.knowledge.enabled = _as_bool(os.getenv("JARVIS_KNOWLEDGE"), self.knowledge.enabled)
        self.scheduler.enabled = _as_bool(os.getenv("JARVIS_SCHEDULER"), self.scheduler.enabled)

        # -- telegram --
        self.telegram.token = os.getenv("TELEGRAM_BOT_TOKEN", self.telegram.token)
        if os.getenv("TELEGRAM_ALLOWED_USERS"):
            self.telegram.allowed_user_ids = _as_list(os.getenv("TELEGRAM_ALLOWED_USERS"))
        self.telegram.enabled = _as_bool(os.getenv("JARVIS_TELEGRAM"), self.telegram.enabled)

        # Built-in providers configured through the classic variables.
        self.providers["openai"] = ProviderConfig(
            name="openai",
            kind="openai",
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", ""),
            vision=True,
        )
        self.providers["anthropic"] = ProviderConfig(
            name="anthropic",
            kind="anthropic",
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            base_url=os.getenv("ANTHROPIC_BASE_URL", ""),
            vision=True,
        )
        self.providers["ollama"] = ProviderConfig(
            name="ollama",
            kind="ollama",
            model=os.getenv("OLLAMA_MODEL", "llama3.1"),
            base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        )
        # NVIDIA NIM is OpenAI-compatible; ideal cloud fallback for a local model.
        self.providers["nim"] = ProviderConfig(
            name="nim",
            kind="openai",
            model=os.getenv("NVIDIA_MODEL", NIM_DEFAULT_MODEL),
            api_key=os.getenv("NVIDIA_API_KEY", os.getenv("NVIDIA_NIM_API_KEY", "")),
            base_url=os.getenv("NVIDIA_BASE_URL", NIM_BASE_URL),
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
        if security.get("allowed_roots") is not None:
            self.allowed_roots = _as_list(security.get("allowed_roots"))
        if security.get("denied_path_patterns") is not None:
            self.denied_path_patterns = _as_list(security.get("denied_path_patterns"))
        if security.get("denied_command_patterns") is not None:
            self.denied_command_patterns = _as_list(security.get("denied_command_patterns"))
        self.audit_log = security.get("audit_log", self.audit_log)

        sandbox = data.get("execution_sandbox") or security.get("execution_sandbox") or {}
        self.execution_sandbox.mode = sandbox.get("mode", self.execution_sandbox.mode)
        self.execution_sandbox.image = sandbox.get("image", self.execution_sandbox.image)
        self.execution_sandbox.network = _as_bool(
            sandbox.get("network", self.execution_sandbox.network), self.execution_sandbox.network
        )
        self.execution_sandbox.workdir = sandbox.get("workdir", self.execution_sandbox.workdir)
        self.execution_sandbox.timeout = int(
            sandbox.get("timeout", self.execution_sandbox.timeout)
        )
        self.execution_sandbox.memory_limit = sandbox.get(
            "memory_limit", self.execution_sandbox.memory_limit
        )

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
        self.interface.overlay = _as_bool(
            interface.get("overlay", self.interface.overlay), self.interface.overlay
        )
        self.interface.notify = _as_bool(
            interface.get("notify", self.interface.notify), self.interface.notify
        )
        self.interface.tray = _as_bool(
            interface.get("tray", self.interface.tray), self.interface.tray
        )
        self.interface.stream = _as_bool(
            interface.get("stream", self.interface.stream), self.interface.stream
        )

        memory = data.get("memory") or {}
        self.memory.persist = _as_bool(
            memory.get("persist", self.memory.persist), self.memory.persist
        )
        self.memory.path = memory.get("path", self.memory.path)
        self.memory.notes_path = memory.get("notes_path", self.memory.notes_path)
        self.memory.max_messages = int(memory.get("max_messages", self.memory.max_messages))
        self.memory.max_chars = int(memory.get("max_chars", self.memory.max_chars))

        router = data.get("router") or {}
        self.router.enabled = _as_bool(router.get("enabled", self.router.enabled), self.router.enabled)
        self.router.primary = router.get("primary", self.router.primary)
        self.router.heavy = router.get("heavy", self.router.heavy)
        self.router.vision = router.get("vision", self.router.vision)
        if router.get("fallbacks") is not None:
            self.router.fallbacks = _as_list(router.get("fallbacks"))
        self.router.escalate_over_chars = int(
            router.get("escalate_over_chars", self.router.escalate_over_chars)
        )

        search = data.get("search") or {}
        self.search.provider = search.get("provider", self.search.provider)
        self.search.tavily_api_key = search.get("tavily_api_key", self.search.tavily_api_key)
        self.search.max_results = int(search.get("max_results", self.search.max_results))
        self.search.depth = search.get("depth", self.search.depth)
        self.search.include_answer = _as_bool(
            search.get("include_answer", self.search.include_answer), self.search.include_answer
        )

        knowledge = data.get("knowledge") or {}
        self.knowledge.enabled = _as_bool(
            knowledge.get("enabled", self.knowledge.enabled), self.knowledge.enabled
        )
        self.knowledge.path = knowledge.get("path", self.knowledge.path)
        self.knowledge.embedding_provider = knowledge.get(
            "embedding_provider", self.knowledge.embedding_provider
        )
        self.knowledge.embedding_model = knowledge.get(
            "embedding_model", self.knowledge.embedding_model
        )
        self.knowledge.top_k = int(knowledge.get("top_k", self.knowledge.top_k))
        self.knowledge.autosave_sessions = _as_bool(
            knowledge.get("autosave_sessions", self.knowledge.autosave_sessions),
            self.knowledge.autosave_sessions,
        )

        scheduler = data.get("scheduler") or {}
        self.scheduler.enabled = _as_bool(
            scheduler.get("enabled", self.scheduler.enabled), self.scheduler.enabled
        )
        self.scheduler.path = scheduler.get("path", self.scheduler.path)
        self.scheduler.tick_seconds = int(
            scheduler.get("tick_seconds", self.scheduler.tick_seconds)
        )
        if scheduler.get("watch_paths") is not None:
            self.scheduler.watch_paths = _as_list(scheduler.get("watch_paths"))

        vision = data.get("vision") or {}
        self.vision.enabled = _as_bool(vision.get("enabled", self.vision.enabled), self.vision.enabled)
        self.vision.provider = vision.get("provider", self.vision.provider)
        self.vision.max_width = int(vision.get("max_width", self.vision.max_width))

        telegram = data.get("telegram") or {}
        self.telegram.enabled = _as_bool(
            telegram.get("enabled", self.telegram.enabled), self.telegram.enabled
        )
        self.telegram.token = telegram.get("token", self.telegram.token)
        if telegram.get("allowed_user_ids") is not None:
            self.telegram.allowed_user_ids = _as_list(telegram.get("allowed_user_ids"))
        self.telegram.allow_confirmations = _as_bool(
            telegram.get("allow_confirmations", self.telegram.allow_confirmations),
            self.telegram.allow_confirmations,
        )

        if data.get("skills_dirs") is not None:
            self.skills_dirs = _as_list(data.get("skills_dirs"))
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
