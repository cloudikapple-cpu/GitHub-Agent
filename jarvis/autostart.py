"""Install or remove a login item so the daemon starts with the system.

Per platform:

* **Windows** - a Task Scheduler logon task. It survives the 'Disable' switch
  in Task Manager's Startup tab, waits thirty seconds so Explorer is ready
  before the hotkey is grabbed, restarts the daemon if it crashes, and runs
  ``pythonw.exe`` so no console window flashes. If ``schtasks`` refuses - a
  locked-down machine, group policy - a Startup-folder shortcut is written
  instead and the failure is reported rather than swallowed.
* **macOS** - a LaunchAgent.
* **Linux** - an XDG autostart entry.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import windows

APP_ID = "com.jarvis.desktop"
TASK_NAME = windows.TASK_NAME
LOGON_DELAY = "PT30S"


def _is_windows() -> bool:
    # Read through the module so tests can pretend to be on Windows.
    return windows.IS_WINDOWS


def _command() -> str:
    executable = windows.pythonw_executable() if _is_windows() else (sys.executable or "python")
    return f'"{executable}" -m jarvis --daemon'


def _appdata() -> Path:
    return Path(os.getenv("APPDATA", str(Path.home())))


def _windows_path() -> Path:
    """The launcher script the scheduled task points at."""

    return _appdata() / "Jarvis" / "jarvis.cmd"


def _startup_path() -> Path:
    """The Startup-folder fallback, used only when Task Scheduler refuses."""

    return _appdata() / "Microsoft/Windows/Start Menu/Programs/Startup/jarvis.cmd"


def _macos_path() -> Path:
    return Path.home() / f"Library/LaunchAgents/{APP_ID}.plist"


def _linux_path() -> Path:
    base = os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / "autostart/jarvis.desktop"


def target_path() -> Path:
    if _is_windows():
        return _windows_path()
    if sys.platform == "darwin":
        return _macos_path()
    return _linux_path()


# ------------------------------------------------------------- task scheduler
def _write_launcher(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"@echo off\r\nstart \"\" {_command()}\r\n", encoding="utf-8")


def _register_task(launcher: Path) -> tuple[bool, str]:
    """Create the logon task. Returns ``(success, detail)``."""

    xml = windows.task_xml(str(launcher), delay=LOGON_DELAY)
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".xml", encoding="utf-16", delete=False, newline=""
    )
    try:
        with handle as stream:
            stream.write(xml)
        proc = windows.schtasks("/Create", "/TN", TASK_NAME, "/XML", handle.name, "/F")
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    finally:
        Path(handle.name).unlink(missing_ok=True)

    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout or "").strip()


def _task_exists() -> bool:
    try:
        proc = windows.schtasks("/Query", "/TN", TASK_NAME)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _remove_task() -> bool:
    try:
        proc = windows.schtasks("/Delete", "/TN", TASK_NAME, "/F")
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


# -------------------------------------------------------------------- public
def install() -> str:
    """Create the autostart entry and return a human-readable summary."""

    path = target_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    executable = sys.executable or "python"

    if _is_windows():
        _write_launcher(path)
        ok, detail = _register_task(path)
        if ok:
            # Two entries would start two daemons; the PID lock would refuse the
            # second one, but the user would still see an error at every logon.
            _startup_path().unlink(missing_ok=True)
            return (
                f"Autostart installed as the scheduled task '{TASK_NAME}' "
                f"(runs {path} 30 seconds after logon)."
            )
        _write_launcher(_startup_path())
        suffix = f" ({detail})" if detail else ""
        return (
            f"Task Scheduler refused{suffix}; installed the Startup shortcut instead: "
            f"{_startup_path()}"
        )

    if sys.platform == "darwin":
        path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            f"  <key>Label</key><string>{APP_ID}</string>\n"
            "  <key>ProgramArguments</key><array>\n"
            f"    <string>{executable}</string><string>-m</string>"
            "<string>jarvis</string><string>--daemon</string>\n"
            "  </array>\n"
            "  <key>RunAtLoad</key><true/>\n"
            "</dict></plist>\n",
            encoding="utf-8",
        )
    else:
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Jarvis\n"
            f"Exec={executable} -m jarvis --daemon\n"
            "X-GNOME-Autostart-enabled=true\n"
            "Terminal=false\n",
            encoding="utf-8",
        )

    return f"Autostart installed: {path}"


def uninstall() -> str:
    path = target_path()
    removed: list[str] = []

    if _is_windows():
        if _task_exists() and _remove_task():
            removed.append(f"scheduled task '{TASK_NAME}'")
        startup = _startup_path()
        if startup.exists():
            startup.unlink()
            removed.append(f"Startup shortcut {startup}")
        if path.exists():
            path.unlink()
            removed.append(f"launcher {path}")
        if removed:
            return "Autostart removed: " + ", ".join(removed) + "."
        return "Autostart was not installed."

    if path.exists():
        path.unlink()
        return f"Autostart removed: {path}"
    return "Autostart was not installed."


def status() -> str:
    path = target_path()

    if _is_windows():
        if _task_exists():
            return f"Autostart enabled via the scheduled task '{TASK_NAME}' (runs {path})."
        startup = _startup_path()
        if startup.exists():
            return f"Autostart enabled via the Startup folder ({startup})."
        return f"Autostart disabled (no '{TASK_NAME}' task, no {startup})."

    return f"Autostart {'enabled' if path.exists() else 'disabled'} ({path})."
