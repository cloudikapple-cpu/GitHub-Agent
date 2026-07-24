"""Global hotkeys — summon Jarvis from anywhere in the OS.

Two backends are tried in order:

1. ``pynput`` — cross-platform, no admin rights on Windows/macOS*;
2. ``keyboard`` — Windows-friendly, needs root on Linux.

\\* macOS requires granting Accessibility + Input Monitoring permission to the
terminal or app running Jarvis (System Settings → Privacy & Security).

Hotkeys are written in the familiar ``ctrl+alt+space`` form and translated to
the backend syntax automatically.
"""

from __future__ import annotations

import threading
from typing import Callable

_SPECIAL = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "alt": "<alt>",
    "option": "<alt>",
    "shift": "<shift>",
    "cmd": "<cmd>",
    "win": "<cmd>",
    "super": "<cmd>",
    "space": "<space>",
    "enter": "<enter>",
    "tab": "<tab>",
    "esc": "<esc>",
}


def to_pynput(combo: str) -> str:
    """Translate ``ctrl+alt+space`` into pynput's ``<ctrl>+<alt>+<space>``."""

    parts = []
    for raw in combo.lower().replace(" ", "").split("+"):
        if not raw:
            continue
        if raw in _SPECIAL:
            parts.append(_SPECIAL[raw])
        elif len(raw) > 1:
            parts.append(f"<{raw}>")
        else:
            parts.append(raw)
    return "+".join(parts)


class HotkeyManager:
    """Register global shortcuts and run callbacks off the listener thread."""

    def __init__(self) -> None:
        self._bindings: dict[str, Callable[[], None]] = {}
        self._listener = None
        self._backend = ""

    def register(self, combo: str, callback: Callable[[], None]) -> None:
        self._bindings[combo] = callback

    # ------------------------------------------------------------------
    def _dispatch(self, callback: Callable[[], None]) -> None:
        # Never block the OS keyboard hook.
        threading.Thread(target=callback, daemon=True).start()

    def start(self) -> str:
        """Start listening. Returns the backend name, or raises RuntimeError."""

        if not self._bindings:
            raise RuntimeError("No hotkeys registered.")

        try:
            from pynput import keyboard as pynput_keyboard

            mapping = {
                to_pynput(combo): (lambda cb=cb: self._dispatch(cb))
                for combo, cb in self._bindings.items()
            }
            self._listener = pynput_keyboard.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
            self._backend = "pynput"
            return self._backend
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001 - e.g. missing macOS permissions
            last_error: Exception | None = exc
        else:  # pragma: no cover
            last_error = None

        try:
            import keyboard as kb

            for combo, cb in self._bindings.items():
                kb.add_hotkey(combo, lambda cb=cb: self._dispatch(cb))
            self._backend = "keyboard"
            return self._backend
        except ImportError as exc:
            raise RuntimeError(
                "Global hotkeys need 'pynput' or 'keyboard'. Install with "
                '`pip install "jarvis-desktop[hotkey]"`.'
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Could not register global hotkeys: {exc}. On Linux the 'keyboard' "
                "backend needs root; on macOS grant Input Monitoring permission."
            ) from exc

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # noqa: BLE001
                pass
            self._listener = None
        if self._backend == "keyboard":
            try:
                import keyboard as kb

                kb.unhook_all_hotkeys()
            except Exception:  # noqa: BLE001
                pass
