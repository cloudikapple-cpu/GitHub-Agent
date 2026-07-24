"""Background daemon: global hotkeys, tray icon, reminders, overlay and voice.

Run it with ``jarvis --daemon``. It stays resident and reacts to:

* ``interface.hotkey``       — opens the window with the text field focused;
* ``interface.voice_hotkey`` — opens the window and starts recording at once;
* the tray icon              — the same actions without a keyboard;
* due reminders and tasks    — notifications, or unattended agent runs;
* Telegram messages          — when the bot is enabled.
"""

from __future__ import annotations

import sys
import threading

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

    # -- reminders and scheduled tasks ---------------------------------
    scheduler = getattr(agent, "scheduler", None)

    def handle_job(job) -> None:
        if job.kind == "task":
            def worker() -> None:
                reply = agent.run(job.text)
                window.push_event("assistant", reply)
                if config.interface.notify:
                    notify("Jarvis — scheduled task", reply[:200])

            threading.Thread(target=worker, name=f"jarvis-{job.id}", daemon=True).start()
            return

        notify("Jarvis — reminder", job.text)
        window.push_event("trace", f"[reminder] {job.text}")
        if voice is not None and config.voice.speak_replies:
            threading.Thread(
                target=lambda: voice.speak(job.text), name="jarvis-speak", daemon=True
            ).start()

    if scheduler is not None:
        scheduler.start(handle_job)
        hint += f", scheduler on ({len(scheduler.list())} jobs)"

    # -- tray icon ------------------------------------------------------
    tray = None
    if config.interface.tray:
        from .tray import TrayIcon

        tray = TrayIcon(
            on_open=open_window,
            on_voice=open_and_listen if voice is not None else open_window,
            on_quit=lambda: window.root.after(0, window.root.quit),
            hotkey=config.interface.hotkey,
        )
        if tray.start():
            hint += ", tray on"

    # -- telegram -------------------------------------------------------
    bot = None
    if config.telegram.enabled:
        from .telegram_bot import TelegramBot

        def telegram_agent(confirm_hook):
            return Agent.from_config(config, confirm_hook=confirm_hook, persist_memory=False)

        bot = TelegramBot(config, telegram_agent)
        try:
            threading.Thread(target=bot.run, name="jarvis-telegram", daemon=True).start()
            hint += ", telegram on"
        except ValueError as exc:
            hint += f", telegram off ({exc})"

    print(hint)
    if config.interface.notify:
        notify("Jarvis", hint)
    window.push_event("trace", hint)

    try:
        window.run()
    finally:
        hotkeys.stop()
        if scheduler is not None:
            scheduler.stop()
        if bot is not None:
            bot.stop()
        if tray is not None and tray.available():
            tray.stop()
    return 0
