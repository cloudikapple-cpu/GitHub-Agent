"""Desktop control tools.

``open_path`` works everywhere with only the standard library. The keyboard,
mouse and screenshot tools require the optional ``pyautogui`` package and a real
graphical desktop session (they will report gracefully if unavailable).
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .base import Tool


def _pyautogui():
    try:
        import pyautogui  # noqa: WPS433 - optional dependency

        return pyautogui
    except Exception:  # noqa: BLE001 - ImportError or display errors
        return None


class OpenPathTool(Tool):
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
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.Popen(["open", target])
            elif system == "Windows":
                os.startfile(target)  # type: ignore[attr-defined]
            else:  # Linux and others
                subprocess.Popen(["xdg-open", target])
        except Exception as exc:  # noqa: BLE001
            return f"Error opening '{target}': {exc}"
        return f"Opened '{target}'."


class ScreenshotTool(Tool):
    name = "take_screenshot"
    description = "Capture a screenshot of the desktop and save it to a PNG file."
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Where to save the PNG (default: ./screenshots/<timestamp>.png).",
            }
        },
    }

    def run(self, path: str | None = None) -> str:
        pg = _pyautogui()
        if pg is None:
            return "Screenshots require the 'pyautogui' package and a graphical session."
        if not path:
            Path("screenshots").mkdir(exist_ok=True)
            path = f"screenshots/{datetime.now():%Y%m%d_%H%M%S}.png"
        try:
            image = pg.screenshot()
            image.save(path)
        except Exception as exc:  # noqa: BLE001
            return f"Error taking screenshot: {exc}"
        return f"Saved screenshot to {path} ({image.size[0]}x{image.size[1]})."


class TypeTextTool(Tool):
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
        pg = _pyautogui()
        if pg is None:
            return "Typing requires the 'pyautogui' package and a graphical session."
        time.sleep(delay)
        try:
            pg.typewrite(text, interval=0.01)
        except Exception as exc:  # noqa: BLE001
            return f"Error typing text: {exc}"
        return f"Typed {len(text)} characters."


class HotkeyTool(Tool):
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
        pg = _pyautogui()
        if pg is None:
            return "Hotkeys require the 'pyautogui' package and a graphical session."
        if not keys:
            return "No keys provided."
        try:
            pg.hotkey(*keys)
        except Exception as exc:  # noqa: BLE001
            return f"Error pressing hotkey: {exc}"
        return f"Pressed {'+'.join(keys)}."
