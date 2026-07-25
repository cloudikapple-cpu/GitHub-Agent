"""Preflight diagnostics for Jarvis.

``jarvis --doctor`` answers the only question that matters before the first
run: will this machine run the assistant, and if not, what exactly is missing.
Every non-passing check carries the command that fixes it, so the report is
actionable without opening the documentation.

Three outcomes are possible per check:

* ``OK``   - nothing to do.
* ``WARN`` - Jarvis starts, but a feature is unavailable.
* ``FAIL`` - Jarvis cannot work until this is fixed.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .config import Config

OK = "ok"
WARN = "warn"
FAIL = "fail"

_MARKS = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[fail]"}

#: The oldest interpreter the package supports (see pyproject.toml).
MIN_PYTHON = (3, 10)
#: Packages behind the desktop control tools.
DESKTOP_MODULES = ("pyautogui", "pyperclip", "psutil", "PIL")
#: Packages behind local speech in and speech out.
VOICE_MODULES = ("faster_whisper", "sounddevice", "pyttsx3")
#: Packages needed when transcription happens in Groq's cloud instead.
HOSTED_VOICE_MODULES = ("sounddevice",)
#: Where the assistant keeps history, jobs, knowledge, trash and the audit log.
STATE_DIR = "~/.jarvis"


@dataclass
class Check:
    """One diagnostic result."""

    name: str
    status: str
    detail: str
    fix: str = ""

    def line(self) -> str:
        text = f"{_MARKS[self.status]} {self.name}: {self.detail}"
        if self.fix and self.status != OK:
            text += f"\n        fix: {self.fix}"
        return text


def _installed(module: str) -> bool:
    """Return True when ``module`` can be imported without importing it."""

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # pragma: no cover - broken installs
        return False


def _missing(modules: tuple[str, ...]) -> list[str]:
    return [name for name in modules if not _installed(name)]


def _origin(config: Config, key: str) -> str:
    """Where a setting came from, for configs built by hand as well as loaded."""

    describe = getattr(config, "describe_source", None)
    return describe(key) if callable(describe) else "default"


def _port_open(url: str, timeout: float = 1.0) -> bool:
    """Return True when something accepts connections at ``url``."""

    target = url if "://" in url else "http://" + url
    parsed = urlparse(target)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ollama_models(host: str) -> list[str]:
    """Models pulled on this machine; empty when the server cannot say."""

    try:
        from .llm.ollama_backend import OllamaBackend

        return OllamaBackend(host=host).list_models()
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        return []


def _writable(path: Path) -> str:
    """Return an empty string when ``path``'s folder can be written to."""

    folder = path.expanduser().parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
        marker = folder / ".doctor"
        marker.write_text("ok", encoding="utf-8")
        marker.unlink()
    except OSError as exc:
        return str(exc)
    return ""


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size = int(size / 1024)
    return f"{size} B"  # pragma: no cover - unreachable


# ----------------------------------------------------------------------
# individual checks
# ----------------------------------------------------------------------
def check_python() -> Check:
    version = platform.python_version()
    system = f"{platform.system()} {platform.release()}".strip()
    required = ".".join(str(part) for part in MIN_PYTHON)
    if tuple(sys.version_info[:2]) < MIN_PYTHON:
        return Check(
            "python",
            FAIL,
            f"{version} is too old; {required} or newer is required",
            f"install Python {required}+ and recreate the virtual environment",
        )
    return Check("python", OK, f"{version} on {system}")


def check_config(config_path: str | None) -> Check:
    if config_path:
        path = Path(config_path).expanduser()
        if path.is_file():
            return Check("config", OK, str(path))
    return Check(
        "config",
        WARN,
        "no config file; built-in defaults and environment variables only",
        "copy config.example.yaml to config.yaml",
    )


def check_env() -> Check:
    if Path(".env").is_file():
        return Check("env file", OK, ".env found in the current folder")
    return Check(
        "env file",
        WARN,
        "no .env in the current folder",
        "copy .env.example to .env and fill in the keys you use",
    )


def check_overrides(config: Config) -> Check | None:
    """List settings that one source took away from another.

    Two files claiming the same setting is the single most confusing thing in
    this configuration system, so the report says who won.
    """

    overrides = list(getattr(config, "overrides", []) or [])
    if not overrides:
        return None
    return Check("overrides", OK, "; ".join(overrides[:5]))


def check_provider(config: Config, probe: bool = True) -> list[Check]:
    """Check the selected provider: model, credentials, reachability, SDK."""

    try:
        provider = config.provider()
    except ValueError as exc:
        return [
            Check(
                "provider",
                FAIL,
                str(exc),
                "set backend in config.yaml or JARVIS_BACKEND in .env",
            )
        ]

    checks = [
        Check(
            "provider",
            OK,
            f"{provider.name} ({provider.kind}), model {provider.model or 'unset'}",
        ),
        Check(
            "settings source",
            OK,
            f"backend from {_origin(config, 'backend')}, "
            f"model from {_origin(config, f'providers.{provider.name}.model')}",
        ),
    ]

    if not provider.model:
        checks.append(
            Check(
                "model",
                FAIL,
                f"provider '{provider.name}' has no model",
                "set providers.<name>.model in config.yaml, or pass --model",
            )
        )

    if provider.kind == "ollama":
        host = provider.base_url or "http://localhost:11434"
        if probe:
            if _port_open(host):
                checks.append(Check("ollama", OK, f"reachable at {host}"))
                checks.extend(_check_ollama_model(host, provider.model))
            else:
                checks.append(
                    Check(
                        "ollama",
                        FAIL,
                        f"nothing is listening at {host}",
                        f"start Ollama, then: ollama pull {provider.model or 'llama3.1'}",
                    )
                )
    elif not provider.api_key:
        checks.append(
            Check(
                "api key",
                FAIL,
                f"provider '{provider.name}' has no API key",
                "add the key to .env, or run with --api-key",
            )
        )
    else:
        checks.append(Check("api key", OK, f"set, {len(provider.api_key)} characters"))

    sdk = {"openai": "openai", "anthropic": "anthropic"}.get(provider.kind)
    if sdk and not _installed(sdk):
        checks.append(
            Check(
                "sdk",
                FAIL,
                f"the '{sdk}' package is not installed",
                f'pip install "jarvis-desktop[{sdk}]"',
            )
        )
    return checks


def _check_ollama_model(host: str, model: str) -> list[Check]:
    """Confirm the configured model is actually pulled.

    A running server with the wrong model produces a 404 mid-conversation,
    which is a bad moment to learn about a missing download.
    """

    models = _ollama_models(host)
    if not models:
        return [
            Check(
                "ollama model",
                WARN,
                "the server did not list its models",
                f"check `ollama list`, then: ollama pull {model or 'llama3.1'}",
            )
        ]
    wanted = (model or "").split(":")[0]
    if any(name.split(":")[0] == wanted for name in models):
        return [Check("ollama model", OK, f"{model} is pulled")]
    return [
        Check(
            "ollama model",
            FAIL,
            f"'{model}' is not pulled; available: {', '.join(models[:5])}",
            f"ollama pull {model}",
        )
    ]


def check_state_dir() -> Check:
    path = Path(STATE_DIR).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
        marker = path / ".doctor"
        marker.write_text("ok", encoding="utf-8")
        marker.unlink()
    except OSError as exc:
        return Check(
            "state folder",
            FAIL,
            f"{path} is not writable: {exc}",
            "check the permissions on your home folder",
        )
    return Check("state folder", OK, f"{path} is writable")


def check_cache(config: Config) -> Check:
    """The reply cache is only useful when its database can be written."""

    cache = config.cache
    if not cache.enabled:
        return Check("reply cache", OK, "off")
    path = Path(cache.path).expanduser()
    problem = _writable(path)
    if problem:
        return Check(
            "reply cache",
            WARN,
            f"{path} is not writable: {problem}",
            "set cache.path to a folder you own, or disable it with --no-cache",
        )
    size = _human_size(path.stat().st_size) if path.exists() else "empty"
    hours = cache.ttl_seconds / 3600
    return Check("reply cache", OK, f"{path} ({size}), entries live {hours:.0f} h")


def check_documents(config: Config) -> Check | None:
    """Report the size of the document index behind retrieval."""

    rag = config.rag
    if not rag.enabled:
        return None
    path = Path(rag.path).expanduser()
    if not path.exists():
        return Check(
            "documents",
            WARN,
            "retrieval is on but nothing is indexed yet",
            "run: jarvis --index <folder>",
        )
    try:
        from .rag import DocumentIndex

        index = DocumentIndex(path=str(path))
        stats = index.stats()
        index.close()
    except Exception as exc:  # noqa: BLE001 - a broken index is a warning, not a crash
        return Check(
            "documents",
            WARN,
            f"the index at {path} could not be read: {exc}",
            "delete the file and run: jarvis --index <folder>",
        )
    if not stats.get("chunks"):
        return Check(
            "documents",
            WARN,
            "the index is empty",
            "run: jarvis --index <folder>",
        )
    return Check(
        "documents",
        OK,
        f"{stats['chunks']} passages from {stats['files']} files",
    )


def check_web(config: Config, probe: bool = True) -> Check | None:
    """The browser interface needs a free port and a loopback binding."""

    web = config.web
    if not web.enabled:
        return None
    if web.host not in {"127.0.0.1", "localhost", "::1"}:
        return Check(
            "web interface",
            WARN,
            f"bound to {web.host}, so anyone on the network can reach it",
            "set web.host to 127.0.0.1 unless you really mean it",
        )
    if probe and _port_open(f"http://{web.host}:{web.port}"):
        return Check(
            "web interface",
            WARN,
            f"port {web.port} is already in use",
            "stop the other Jarvis, or set web.port to a free port",
        )
    return Check("web interface", OK, f"http://{web.host}:{web.port}, token required")


def check_keychain(config: Config) -> Check:
    """Say whether ``keyring:NAME`` references can be resolved on this machine."""

    try:
        from .secrets import available, backend_name
    except Exception:  # noqa: BLE001 - defensive
        return Check("keychain", WARN, "the secrets module could not be loaded")
    if available():
        return Check("keychain", OK, f"{backend_name()}; use keyring:NAME in config.yaml")
    uses_keyring = any(
        str(getattr(provider, "api_key", "")).startswith("keyring:")
        for provider in config.providers.values()
    )
    return Check(
        "keychain",
        WARN if uses_keyring else OK,
        "no keychain backend; secrets come from .env only",
        'pip install "jarvis-desktop[keyring]"',
    )


def check_features(config: Config) -> list[Check]:
    """Check the optional packages behind desktop, hotkeys, voice and search."""

    checks: list[Check] = []

    missing = _missing(DESKTOP_MODULES)
    if missing:
        checks.append(
            Check(
                "desktop control",
                WARN,
                "missing " + ", ".join(missing),
                'pip install "jarvis-desktop[desktop]"',
            )
        )
    else:
        checks.append(
            Check("desktop control", OK, "screenshots, keyboard, clipboard and processes")
        )

    if _installed("pynput"):
        checks.append(
            Check(
                "global hotkey",
                OK,
                f"{config.interface.hotkey}, voice on {config.interface.voice_hotkey}",
            )
        )
    else:
        checks.append(
            Check(
                "global hotkey",
                WARN,
                "pynput is not installed, so the hotkeys do nothing",
                'pip install "jarvis-desktop[hotkey]"',
            )
        )

    if config.interface.tray and not _installed("pystray"):
        checks.append(
            Check(
                "tray icon",
                WARN,
                "the tray icon is enabled but pystray is not installed",
                'pip install "jarvis-desktop[tray]"',
            )
        )

    if config.voice.enabled:
        checks.append(check_voice(config))

    if config.search.tavily_api_key:
        checks.append(Check("web search", OK, "Tavily key present"))
    elif _installed("duckduckgo_search"):
        checks.append(Check("web search", OK, "DuckDuckGo fallback"))
    else:
        checks.append(
            Check(
                "web search",
                WARN,
                "no Tavily key and no DuckDuckGo package",
                'add TAVILY_API_KEY to .env, or pip install "jarvis-desktop[web]"',
            )
        )
    return checks


def check_voice(config: Config) -> Check:
    """Voice needs a microphone plus one working transcription engine."""

    engine = (config.voice.stt or "auto").lower()
    hosted = engine == "groq" or (
        engine == "auto"
        and bool(os.getenv("GROQ_API_KEY") or getattr(config.voice, "stt_api_key", ""))
    )

    if hosted:
        missing = _missing(HOSTED_VOICE_MODULES)
        if missing:
            return Check(
                "voice",
                FAIL,
                "voice is enabled but missing " + ", ".join(missing),
                'pip install "jarvis-desktop[voice]"',
            )
        if not os.getenv("GROQ_API_KEY") and not getattr(config.voice, "stt_api_key", ""):
            return Check(
                "voice",
                FAIL,
                "transcription is set to Groq but there is no key",
                "add GROQ_API_KEY to .env (free: https://console.groq.com/keys)",
            )
        return Check("voice", OK, f"Groq Whisper in, {config.voice.tts} out")

    missing_voice = _missing(VOICE_MODULES)
    if missing_voice:
        return Check(
            "voice",
            FAIL,
            "voice is enabled but missing " + ", ".join(missing_voice),
            'pip install "jarvis-desktop[voice]", or set voice.stt: groq with GROQ_API_KEY',
        )
    return Check("voice", OK, f"{config.voice.stt} in, {config.voice.tts} out")


def check_platform(config: Config) -> list[Check]:
    """Check the external programs the tools shell out to."""

    checks: list[Check] = []

    if platform.system() == "Windows":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell:
            checks.append(Check("powershell", OK, shell))
        else:
            checks.append(
                Check(
                    "powershell",
                    WARN,
                    "neither pwsh nor powershell is on PATH",
                    "set JARVIS_POWERSHELL to the full path of powershell.exe",
                )
            )
        if config.allow_app_management:
            if shutil.which("winget"):
                checks.append(Check("winget", OK, "installing and removing apps is available"))
            else:
                checks.append(
                    Check(
                        "winget",
                        WARN,
                        "app management is allowed but winget is not on PATH",
                        "install App Installer from the Microsoft Store",
                    )
                )

    mode = config.execution_sandbox.mode
    if mode == "docker" and not shutil.which("docker"):
        checks.append(
            Check(
                "sandbox",
                FAIL,
                "the sandbox is set to docker but docker is not on PATH",
                "start Docker Desktop, or run with --sandbox none",
            )
        )
    elif mode == "firejail" and not shutil.which("firejail"):
        checks.append(
            Check(
                "sandbox",
                FAIL,
                "the sandbox is set to firejail but firejail is not installed",
                "install firejail, or run with --sandbox none",
            )
        )
    return checks


def check_permissions(config: Config) -> Check:
    """Summarise what the assistant is allowed to do on this machine."""

    granted = [
        name
        for name, allowed in (
            ("shell", config.allow_shell),
            ("code", config.allow_exec),
            ("keyboard and screen", config.allow_desktop),
            ("app installs", config.allow_app_management),
            ("network", config.allow_network),
        )
        if allowed
    ]
    detail = ", ".join(granted) if granted else "nothing, this is read-only mode"
    if not config.require_confirmation and (config.allow_shell or config.allow_exec):
        return Check(
            "permissions",
            WARN,
            f"{detail}; confirmations are off",
            "drop --yolo / --no-confirm unless you mean it",
        )
    return Check("permissions", OK, detail)


# ----------------------------------------------------------------------
# report
# ----------------------------------------------------------------------
def diagnose(config: Config, config_path: str | None = None, probe: bool = True) -> list[Check]:
    """Run every check and return the results in reading order."""

    checks = [check_python(), check_config(config_path), check_env()]
    overrides = check_overrides(config)
    if overrides is not None:
        checks.append(overrides)
    checks.extend(check_provider(config, probe=probe))
    checks.append(check_state_dir())
    checks.append(check_cache(config))
    documents = check_documents(config)
    if documents is not None:
        checks.append(documents)
    web = check_web(config, probe=probe)
    if web is not None:
        checks.append(web)
    checks.append(check_keychain(config))
    checks.extend(check_features(config))
    checks.extend(check_platform(config))
    checks.append(check_permissions(config))
    return checks


def has_failures(checks: list[Check]) -> bool:
    return any(check.status == FAIL for check in checks)


def format_report(checks: list[Check]) -> str:
    """Render the checks as a human-readable report."""

    failures = sum(1 for check in checks if check.status == FAIL)
    warnings = sum(1 for check in checks if check.status == WARN)
    lines = [check.line() for check in checks]
    lines.append("")
    if failures:
        lines.append(
            f"{failures} blocking problem(s) and {warnings} warning(s). "
            "Jarvis will not run until the blocking problems are fixed."
        )
    elif warnings:
        lines.append(
            f"No blocking problems, {warnings} warning(s). "
            "Jarvis will run; the features above are unavailable."
        )
    else:
        lines.append("Everything checks out. Run 'jarvis' to start.")
    return "\n".join(lines)
