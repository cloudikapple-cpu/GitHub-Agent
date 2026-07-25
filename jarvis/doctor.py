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

#: Packages behind the desktop control tools.
DESKTOP_MODULES = ("pyautogui", "pyperclip", "psutil", "PIL")
#: Packages behind speech in and speech out.
VOICE_MODULES = ("faster_whisper", "sounddevice", "pyttsx3")
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


def _port_open(url: str, timeout: float = 1.0) -> bool:
    """Return True when something accepts connections at ``url``."""

    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ----------------------------------------------------------------------
# individual checks
# ----------------------------------------------------------------------
def check_python() -> Check:
    version = platform.python_version()
    system = f"{platform.system()} {platform.release()}".strip()
    if sys.version_info < (3, 10):
        return Check(
            "python",
            FAIL,
            f"{version} is too old",
            "install Python 3.10 or newer and recreate the virtual environment",
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
        )
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
        missing_voice = _missing(VOICE_MODULES)
        if missing_voice:
            checks.append(
                Check(
                    "voice",
                    FAIL,
                    "voice is enabled but missing " + ", ".join(missing_voice),
                    'pip install "jarvis-desktop[voice]"',
                )
            )
        else:
            checks.append(Check("voice", OK, f"{config.voice.stt} in, {config.voice.tts} out"))

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
def diagnose(
    config: Config, config_path: str | None = None, probe: bool = True
) -> list[Check]:
    """Run every check and return the results in reading order."""

    checks = [check_python(), check_config(config_path), check_env()]
    checks.extend(check_provider(config, probe=probe))
    checks.append(check_state_dir())
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
