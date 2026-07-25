"""Desktop control tools.

``open_path`` works everywhere with only the standard library. The keyboard,
mouse and screenshot tools require the optional ``pyautogui`` package and a real
graphical desktop session (they will report gracefully if unavailable).

Every tool in this module is guarded by a :class:`~jarvis.security.SecurityPolicy`:

* ``allow_desktop`` gates keyboard, mouse and screen capture entirely;
* ``open_path`` resolves its target through ``check_path`` so ``allowed_roots``
  and the denied-path patterns apply;
* opening an executable counts as running a command, so it additionally
  requires ``allow_shell`` — otherwise ``open_path`` would be a trivial way
  around a disabled shell;
* opening a URL requires ``allow_network``.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from datetime import datetime
from pathlib import Path

from ..security import SecurityError, SecurityPolicy
from .base import Tool

#: Schemes that ``open_path`` treats as a network target rather than a file.
URL_PREFIXES = ("http://", "https://", "ftp://", "mailto:")

#: Extensions the operating system executes rather than opens in a viewer.
#: The Windows list matters most — double-clicking any of these runs code.
EXECUTABLE_SUFFIXES = {
    ".exe",
    ".com",
    ".bat",
    ".cmd",
    ".msi",
    ".ps1",
    ".vbs",
    ".vbe",
    ".js",
    ".jse",
    ".wsf",
    ".wsh",
    ".scr",
    ".cpl",
    ".reg",
    ".lnk",
    ".sh",
    ".command",
    ".app",
}


def _pyautogui():
    try:
        import pyautogui  # noqa: WPS433 - optional dependency

        return pyautogui
    except Exception:  # noqa: BLE001 - ImportError or display errors
        return None


class _DesktopTool(Tool):
    """Base class wiring a security policy into every desktop tool."""

    def __init__(self, policy: SecurityPolicy | None = None):
        self.policy = policy or SecurityPolicy()

    def _guard(self) -> None:
        """Raise :class:`SecurityError` when desktop control is disabled."""

        self.policy.check_desktop()


class OpenPathTool(_DesktopTool):
    name = "open_path"
    description = (
        "Open a file, folder, application or URL with the operating system's "
        "default handler (like double-clicking it)."
    )
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "A file path, folder, app name/path, or URL (http/https).",
            }
        },
        "required": ["target"],
    }

    def run(self, target: str) -> str:
        self._guard()

        if target.lower().startswith(URL_PREFIXES):
            self.policy.check_network()
            self.policy.audit("open_url", target)
            resolved: str = target
        else:
            path = self.policy.check_path(target)
            if path.suffix.lower() in EXECUTABLE_SUFFIXES:
                # Launching a binary is code execution by another name.
                if not self.policy.allow_shell:
                    raise SecurityError(
                        f"Opening '{path.name}' would execute it, and shell "
                        "execution is disabled (set JARVIS_ALLOW_SHELL=true)."
                    )
                self.policy.audit("open_executable", str(path))
            resolved = str(path)

        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.Popen(["open", resolved])
            elif system == "Windows":
                os.startfile(resolved)  # type: ignore[attr-defined]
            else:  # Linux and others
                subprocess.Popen(["xdg-open", resolved])
        except Exception as exc:  # noqa: BLE001
            return f"Error opening '{resolved}': {exc}"
        return f"Opened '{resolved}'."


class ScreenshotTool(_DesktopTool):
    name = "take_screenshot"
    description = "Capture a screenshot of the desktop and save it to a PNG file."
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Where to save the PNG "
                    "(default: ~/.jarvis/screenshots/<timestamp>.png)."
                ),
            }
        },
    }

    def run(self, path: str | None = None) -> str:
        self._guard()
        if not path:
            path = str(
                Path.home()
                / ".jarvis"
                / "screenshots"
                / f"{datetime.now():%Y%m%d_%H%M%S}.png"
            )
        target = self.policy.check_path(path, write=True)

        pg = _pyautogui()
        if pg is None:
            return "Screenshots require the 'pyautogui' package and a graphical session."
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            image = pg.screenshot()
            image.save(target)
        except Exception as exc:  # noqa: BLE001
            return f"Error taking screenshot: {exc}"
        return f"Saved screenshot to {target} ({image.size[0]}x{image.size[1]})."


class TypeTextTool(_DesktopTool):
    name = "type_text"
    description = "Type text using the keyboard into the currently focused window."
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to type."},
            "delay": {
                "type": "number",
                "description": "Seconds to wait before typing, to let a window focus (default 1).",
                "default": 1,
            },
        },
        "required": ["text"],
    }

    def run(self, text: str, delay: float = 1) -> str:
        self._guard()
        pg = _pyautogui()
        if pg is None:
            return "Typing requires the 'pyautogui' package and a graphical session."
        self.policy.audit("type_text", text)
        time.sleep(delay)
        try:
            pg.typewrite(text, interval=0.01)
        except Exception as exc:  # noqa: BLE001
            return f"Error typing text: {exc}"
        return f"Typed {len(text)} characters."


class HotkeyTool(_DesktopTool):
    name = "press_hotkey"
    description = "Press a keyboard shortcut, e.g. ['ctrl', 'c'] or ['cmd', 'space']."
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keys to press together, e.g. ['ctrl', 'shift', 't'].",
            }
        },
        "required": ["keys"],
    }

    def run(self, keys: list[str]) -> str:
        self._guard()
        if not keys:
            return "No keys provided."
        pg = _pyautogui()
        if pg is None:
            return "Hotkeys require the 'pyautogui' package and a graphical session."
        self.policy.audit("press_hotkey", "+".join(keys))
        try:
            pg.hotkey(*keys)
        except Exception as exc:  # noqa: BLE001
            return f"Error pressing hotkey: {exc}"
        return f"Pressed {'+'.join(keys)}."
