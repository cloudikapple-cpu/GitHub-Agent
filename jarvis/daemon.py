"""Background daemon: global hotkeys + overlay window + voice.

Run it with ``jarvis --daemon``. It stays resident and reacts to:

* ``interface.hotkey``       — opens the window with the text field focused;
* ``interface.voice_hotkey`` — opens the window and starts recording at once.
"""

from __future__ import annotations

import sys

from .agent import Agent
from .config import Config
from .hotkey import HotkeyManager
from .notifications import notify


def run_daemon(config: Config | None = None) -> int:
    config = config or Config.load()

    from .ui import TK_AVAILABLE, AssistantWindow

    if not TK_AVAILABLE:
        print("The daemon needs Tkinter (install 'python3-tk' on Linux).", file=sys.stderr)
        return 1

    voice = None
    if config.voice.enabled:
        from .voice import VoiceIO

        voice = VoiceIO(config.voice)

    window: AssistantWindow | None = None

    def confirm(tool_name, arguments) -> bool:
        if window is None:
            return False
        return window.confirm(tool_name, arguments)

    def on_event(line: str) -> None:
        if window is not None:
            window.push_event("trace", line)

    agent = Agent.from_config(config, confirm_hook=confirm, on_event=on_event)
    window = AssistantWindow(agent, voice=voice)

    hotkeys = HotkeyManager()

    def open_window() -> None:
        window.root.after(0, window.show)

    def open_and_listen() -> None:
        window.root.after(0, window.show)
        window.root.after(150, window.listen)

    hotkeys.register(config.interface.hotkey, open_window)
    if voice is not None and config.interface.voice_hotkey:
        hotkeys.register(config.interface.voice_hotkey, open_and_listen)

    try:
        backend = hotkeys.start()
        hint = f"Hotkeys active via {backend}: {config.interface.hotkey}"
        if voice is not None:
            hint += f", voice: {config.interface.voice_hotkey}"
    except RuntimeError as exc:
        hint = f"Hotkeys unavailable ({exc})"

    print(hint)
    if config.interface.notify:
        notify("Jarvis", hint)
    window.push_event("trace", hint)

    try:
        window.run()
    finally:
        hotkeys.stop()
    return 0
