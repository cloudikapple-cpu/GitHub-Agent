"""Global hotkeys - summon Jarvis from anywhere in the OS.

Two backends are tried in order:

1. ``pynput`` - cross-platform, no admin rights on Windows/macOS*;
2. ``keyboard`` - Windows-friendly, needs root on Linux.

\\* macOS requires granting Accessibility + Input Monitoring permission to the
terminal or app running Jarvis (System Settings -> Privacy & Security).

Hotkeys are written in the familiar ``ctrl+alt+space`` form and translated to
the backend syntax automatically.

Both backends fail silently when another application already owns a shortcut:
the listener starts, the key does nothing, and there is no way to tell from the
logs. :meth:`HotkeyManager.conflicts` asks Windows directly before starting, so
the daemon can report the clash instead of looking broken.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from . import windows

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
    def conflicts(self) -> list[str]:
        """Registered combinations that another application already owns.

        Empty on platforms where the question cannot be answered, so callers
        can treat 'no conflicts' and 'unknown' the same way.
        """

        taken = []
        for combo in self._bindings:
            if windows.hotkey_available(combo) is False:
                taken.append(combo)
        return taken

    def _dispatch(self, callback: Callable[[], None]) -> None:
        # Never block the OS keyboard hook.
        threading.Thread(target=callback, daemon=True).start()

    def _start_pynput(self) -> None:
        from pynput import keyboard as pynput_keyboard

        mapping = {
            to_pynput(combo): (lambda cb=cb: self._dispatch(cb))
            for combo, cb in self._bindings.items()
        }
        listener = pynput_keyboard.GlobalHotKeys(mapping)
        listener.daemon = True
        listener.start()
        self._listener = listener

    def _start_keyboard(self) -> None:
        import keyboard as kb

        for combo, cb in self._bindings.items():
            kb.add_hotkey(combo, lambda cb=cb: self._dispatch(cb))

    def start(self) -> str:
        """Start listening. Returns the backend name, or raises RuntimeError.

        Each backend is tried in turn; the last failure is reported if none of
        them works (missing package, missing macOS permission, no root on X11).
        """

        if not self._bindings:
            raise RuntimeError("No hotkeys registered.")

        errors: list[str] = []
        for name, starter in (("pynput", self._start_pynput), ("keyboard", self._start_keyboard)):
            try:
                starter()
            except ImportError:
                errors.append(f"{name}: not installed")
            except Exception as exc:  # noqa: BLE001 - backend availability varies by OS
                errors.append(f"{name}: {exc}")
            else:
                self._backend = name
                return name

        raise RuntimeError(
            "Could not register global hotkeys ("
            + "; ".join(errors)
            + "). Install with `pip install \"jarvis-desktop[hotkey]\"`. "
            "On Linux the 'keyboard' backend needs root; on macOS grant Input "
            "Monitoring permission to your terminal."
        )

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
        self._backend = ""
