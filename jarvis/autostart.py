"""Install or remove a login item so the daemon starts with the system.

Supported: Windows (Startup shortcut via a .cmd file), macOS (LaunchAgent) and
Linux (XDG autostart .desktop entry).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "com.jarvis.desktop"


def _command() -> str:
    executable = sys.executable or "python"
    return f'"{executable}" -m jarvis --daemon'


def _windows_path() -> Path:
    base = os.getenv("APPDATA", str(Path.home()))
    return Path(base) / "Microsoft/Windows/Start Menu/Programs/Startup/jarvis.cmd"


def _macos_path() -> Path:
    return Path.home() / f"Library/LaunchAgents/{APP_ID}.plist"


def _linux_path() -> Path:
    base = os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / "autostart/jarvis.desktop"


def target_path() -> Path:
    if sys.platform.startswith("win"):
        return _windows_path()
    if sys.platform == "darwin":
        return _macos_path()
    return _linux_path()


def install() -> str:
    """Create the autostart entry and return a human-readable summary."""

    path = target_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    executable = sys.executable or "python"

    if sys.platform.startswith("win"):
        path.write_text(f"@echo off\r\nstart \"\" {_command()}\r\n", encoding="utf-8")
    elif sys.platform == "darwin":
        path.write_text(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
            "\"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
            "<plist version=\"1.0\"><dict>\n"
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
    if path.exists():
        path.unlink()
        return f"Autostart removed: {path}"
    return "Autostart was not installed."


def status() -> str:
    path = target_path()
    return f"Autostart {'enabled' if path.exists() else 'disabled'} ({path})."
