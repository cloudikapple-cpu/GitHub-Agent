"""Background daemon: global hotkeys, tray icon, reminders, overlay, web and voice.

Run it with ``jarvis --daemon``. It stays resident and reacts to:

* ``interface.hotkey``       - opens the window with the text field focused;
* ``interface.voice_hotkey`` - opens the window and starts recording at once;
* the tray icon              - the same actions without a keyboard;
* due reminders and tasks    - notifications, or unattended agent runs;
* the browser interface      - when ``web.enabled`` is set;
* Telegram messages          - when the bot is enabled.

While it runs it also keeps a short clipboard history, so 'what did I copy
before this?' has an answer.

Only one daemon may run at a time: a second one would duplicate every reminder
and fight over the global hotkey, so startup is guarded by a PID lock.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING

from .agent import Agent
from .clipboard import ClipboardWatcher
from .config import Config
from .hotkey import HotkeyManager
from .notifications import notify
from .singleton import AlreadyRunning, SingleInstance

if TYPE_CHECKING:  # pragma: no cover - Tkinter is optional at runtime
    from .ui import AssistantWindow

LOGGER = logging.getLogger(__name__)


def run_daemon(config: Config | None = None) -> int:
    """Start the resident assistant, refusing to run twice."""

    config = config or Config.load()

    from .ui import TK_AVAILABLE

    if not TK_AVAILABLE:
        print("The daemon needs Tkinter (install 'python3-tk' on Linux).", file=sys.stderr)
        return 1

    lock = SingleInstance()
    try:
        lock.acquire()
    except AlreadyRunning as exc:
        print(
            f"{exc} Reach it with the hotkey or the tray icon, "
            "or stop that process before starting a new daemon.",
            file=sys.stderr,
        )
        return 1

    try:
        return _run(config)
    finally:
        lock.release()


def _run(config: Config) -> int:
    from .ui import AssistantWindow

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
    window = AssistantWindow(
        agent, voice=voice, stream=getattr(config.interface, "stream", False)
    )

    hotkeys = HotkeyManager()

    def open_window() -> None:
        window.root.after(0, window.show)

    def open_and_listen() -> None:
        window.root.after(0, window.show)
        if voice is not None:
            window.root.after(150, window.listen)

    hotkeys.register(config.interface.hotkey, open_window)
    if config.interface.voice_hotkey:
        # Registered even when voice is off: a shortcut that opens the window
        # is more useful than one that silently does nothing.
        hotkeys.register(config.interface.voice_hotkey, open_and_listen)

    # Ask the OS before starting: a shortcut owned by another application would
    # register without error and then simply never fire.
    taken = hotkeys.conflicts()

    try:
        backend = hotkeys.start()
        hint = f"Hotkeys active via {backend}: {config.interface.hotkey} (window)"
        if config.interface.voice_hotkey:
            role = "voice" if voice is not None else "window"
            hint += f", {config.interface.voice_hotkey} ({role})"
    except RuntimeError as exc:
        hint = f"Hotkeys unavailable ({exc})"

    if taken:
        hint += (
            "; already owned by another application: "
            + ", ".join(taken)
            + " - change interface.hotkey in config.yaml or JARVIS_HOTKEY"
        )

    # -- clipboard history ---------------------------------------------
    clipboard = ClipboardWatcher(getattr(agent.tools, "clipboard", None))
    if clipboard.start():
        hint += ", clipboard history on"

    # -- reminders and scheduled tasks ---------------------------------
    scheduler = agent.scheduler

    def handle_job(job) -> None:
        if job.kind == "task":

            def worker() -> None:
                try:
                    reply = agent.run(job.text)
                except Exception as exc:  # noqa: BLE001 - a bad job must not kill the loop
                    LOGGER.exception("Scheduled task failed")
                    reply = f"Scheduled task failed: {exc}"
                window.push_event("assistant", reply)
                if config.interface.notify:
                    notify("Jarvis - scheduled task", reply[:200])

            threading.Thread(target=worker, name=f"jarvis-{job.id}", daemon=True).start()
            return

        notify("Jarvis - reminder", job.text)
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

    # -- browser interface ----------------------------------------------
    web = None
    if getattr(config, "web", None) is not None and config.web.enabled:
        from .webui import WebServer

        candidate = WebServer(
            agent,
            host=config.web.host,
            port=config.web.port,
            token=config.web.token,
            stream=getattr(config.interface, "stream", True),
        )
        try:
            url = candidate.start()
        except OSError as exc:
            # A busy port is a configuration problem, not a reason to refuse
            # to run the rest of the daemon.
            hint += f", web off ({exc})"
        else:
            web = candidate
            hint += f", web at {url}"
            if config.web.open_browser:
                web.open_in_browser()

    # -- telegram -------------------------------------------------------
    bot = None
    if config.telegram.enabled:
        from .telegram_bot import TelegramBot

        def telegram_agent(confirm_hook):
            return Agent.from_config(config, confirm_hook=confirm_hook, persist_memory=False)

        candidate_bot = TelegramBot(config, telegram_agent)
        try:
            candidate_bot.validate()
        except ValueError as exc:
            hint += f", telegram off ({exc})"
        else:
            bot = candidate_bot
            threading.Thread(target=bot.run, name="jarvis-telegram", daemon=True).start()
            hint += ", telegram on"

    print(hint)
    if config.interface.notify:
        notify("Jarvis", hint)
    window.push_event("trace", hint)

    try:
        window.run()
    finally:
        hotkeys.stop()
        clipboard.stop()
        if scheduler is not None:
            scheduler.stop()
        if web is not None:
            web.stop()
        if bot is not None:
            bot.stop()
        if tray is not None:
            tray.stop()
    return 0
