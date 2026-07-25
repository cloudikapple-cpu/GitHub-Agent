"""Command line interface: one-shot, REPL, GUI, daemon and Telegram modes."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .agent import Agent
from .config import Config

try:  # optional pretty output
    from rich.console import Console
    from rich.markdown import Markdown

    _console: Any = Console()
except ImportError:  # pragma: no cover
    _console = None

BANNER = """Jarvis — desktop AI assistant
Type a request, 'reset' to clear the conversation, or 'exit' to quit.
"""

#: Ready-made permission sets, so the user does not have to juggle five
#: JARVIS_ALLOW_* switches. Explicit flags still win: the profile is applied
#: before them.
PROFILES: dict[str, dict[str, bool]] = {
    # Reading and searching only: no shell, no code, no keyboard, no installs.
    "safe": {
        "require_confirmation": True,
        "allow_shell": False,
        "allow_exec": False,
        "allow_desktop": False,
        "allow_app_management": False,
    },
    # The everyday setting: full control, but it asks before risky actions.
    "dev": {
        "require_confirmation": True,
        "allow_shell": True,
        "allow_exec": True,
        "allow_desktop": True,
        "allow_app_management": False,
    },
    # No brakes. Everything allowed, nothing confirmed.
    "yolo": {
        "require_confirmation": False,
        "allow_shell": True,
        "allow_exec": True,
        "allow_desktop": True,
        "allow_app_management": True,
    },
}


def _print(text: str, style: str | None = None) -> None:
    if _console is not None:
        _console.print(text, style=style)
    else:
        print(text)


def _print_markdown(text: str) -> None:
    if _console is not None:
        _console.print(Markdown(text))
    else:
        print(text)


def _confirm(tool_name: str, arguments: dict[str, Any]) -> bool:
    _print(f"\nJarvis wants to run: {tool_name}", style="yellow")
    for key, value in arguments.items():
        preview = str(value)
        if len(preview) > 500:
            preview = preview[:500] + "…"
        _print(f"  {key}: {preview}", style="yellow")
    try:
        answer = input("Allow? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in {"y", "yes"}


def _make_event_hook(verbose: bool):
    if not verbose:
        return None

    def hook(line: str) -> None:
        _print(line, style="dim")

    return hook


def apply_profile(config: Config, name: str) -> Config:
    """Apply a named permission profile to ``config``."""

    for attribute, value in PROFILES[name].items():
        setattr(config, attribute, value)
    return config


def apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    """Apply command-line overrides to a loaded config."""

    # The profile goes first so individual flags can still override it.
    if getattr(args, "profile", None):
        apply_profile(config, args.profile)

    if args.backend:
        config.backend = args.backend
        config.router.enabled = False
    if args.model:
        config.provider().model = args.model
    if args.api_base:
        config.provider().base_url = args.api_base
    if args.api_key:
        config.provider().api_key = args.api_key
    if args.router:
        config.router.enabled = True
    if args.no_router:
        config.router.enabled = False
    if args.no_confirm:
        config.require_confirmation = False
    if args.yolo:
        apply_profile(config, "yolo")
    if args.dry_run:
        config.dry_run = True
    if args.voice:
        config.voice.enabled = True
    if args.sandbox:
        config.execution_sandbox.mode = args.sandbox
    if getattr(args, "stream", False):
        config.interface.stream = True
    if getattr(args, "no_stream", False):
        config.interface.stream = False
    return config


def build_agent(args: argparse.Namespace) -> tuple[Agent, Config]:
    config = apply_overrides(Config.load(args.config), args)
    agent = Agent.from_config(
        config,
        confirm_hook=_confirm,
        on_event=_make_event_hook(args.verbose),
    )
    return agent, config


def respond(agent: Agent, config: Config, message: str) -> str:
    """Answer one message, streaming the reply when the config asks for it."""

    if not getattr(config.interface, "stream", False):
        reply = agent.run(message)
        _print_markdown(reply)
        return reply

    chunks: list[str] = []
    for chunk in agent.stream(message):
        chunks.append(chunk)
        print(chunk, end="", flush=True)
    print()
    return "".join(chunks)


def run_once(agent: Agent, message: str, config: Config | None = None) -> int:
    if config is None:
        reply = agent.run(message)
        _print_markdown(reply)
    else:
        respond(agent, config, message)
    return 0


def run_repl(agent: Agent, voice=None, config: Config | None = None) -> int:
    _print(BANNER, style="bold")
    while True:
        try:
            if voice is not None:
                input("Press Enter to speak…")
                user_input = voice.listen()
                _print(f"You: {user_input}", style="cyan")
            else:
                user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            _print("\nBye.")
            return 0

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", ":q"}:
            _print("Bye.")
            return 0
        if user_input.lower() in {"reset", "clear"}:
            agent.memory.reset()
            _print("Conversation cleared.", style="dim")
            continue
        if user_input.lower() in {"tools", ":tools"}:
            _print(agent.tools.describe())
            continue
        if user_input.lower() in {"undo", ":undo"}:
            _print(agent.tools.execute("undo_last", {}))
            continue
        if user_input.lower() in {"usage", ":usage"}:
            from .budget import default_tracker

            _print(default_tracker().report())
            continue

        try:
            if config is None:
                reply = agent.run(user_input)
                _print_markdown(reply)
            else:
                reply = respond(agent, config, user_input)
        except KeyboardInterrupt:
            agent.cancel()
            _print("Interrupted.", style="dim")
            continue
        if voice is not None and voice.config.speak_replies:
            voice.speak(reply)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis", description="Jarvis — an extensible desktop AI assistant."
    )
    parser.add_argument("-m", "--message", help="Run a single request and exit.")
    parser.add_argument(
        "-b",
        "--backend",
        help="Provider name from your config (openai, anthropic, ollama, nim, or a custom one).",
    )
    parser.add_argument("--model", help="Override the model for this run.")
    parser.add_argument("--api-base", help="Override the API base URL (any OpenAI-compatible API).")
    parser.add_argument("--api-key", help="Override the API key for this run.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        help="Permission preset: safe (read-only), dev (full control, confirms), yolo (no brakes).",
    )
    parser.add_argument(
        "--router",
        action="store_true",
        help="Enable provider routing (local model first, cloud fallback).",
    )
    parser.add_argument("--no-router", action="store_true", help="Disable provider routing.")
    parser.add_argument("-c", "--config", default="config.yaml", help="Path to the config file.")
    parser.add_argument("--no-confirm", action="store_true", help="Do not ask before risky actions.")
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="Shorthand for --profile yolo. Use at your own risk.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only: print the actions that would be taken, run nothing.",
    )
    parser.add_argument(
        "--sandbox",
        choices=["none", "docker", "firejail"],
        help="Run shell commands and code inside an isolated sandbox.",
    )
    parser.add_argument(
        "--stream", action="store_true", help="Print the reply as it is generated."
    )
    parser.add_argument(
        "--no-stream", action="store_true", help="Wait for the full reply before printing."
    )
    parser.add_argument("--voice", action="store_true", help="Use the microphone for input.")
    parser.add_argument("--gui", action="store_true", help="Open the desktop window.")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run in the background with hotkeys, tray icon and reminders.",
    )
    parser.add_argument(
        "--telegram", action="store_true", help="Run the Telegram bot in the foreground."
    )
    parser.add_argument(
        "--autostart",
        choices=["install", "remove", "status"],
        help="Manage starting the daemon at login.",
    )
    parser.add_argument(
        "--usage",
        nargs="?",
        const="today",
        metavar="DAY",
        help="Print token and spend accounting for today (or for YYYY-MM-DD) and exit.",
    )
    parser.add_argument("--list-tools", action="store_true", help="Print available tools and exit.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show tool calls and results.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.usage:
        # Accounting is read straight from the ledger: no provider, no API key
        # and no config file are needed to answer 'what did today cost?'.
        from .budget import default_tracker

        day = None if args.usage == "today" else args.usage
        _print(default_tracker().report(day))
        return 0

    if args.autostart:
        from . import autostart

        action = {
            "install": autostart.install,
            "remove": autostart.uninstall,
            "status": autostart.status,
        }[args.autostart]
        _print(action())
        return 0

    if args.daemon:
        from .daemon import run_daemon

        return run_daemon(apply_overrides(Config.load(args.config), args))

    if args.telegram:
        from .telegram_bot import TelegramBot

        config = apply_overrides(Config.load(args.config), args)
        config.telegram.enabled = True

        def telegram_agent(confirm_hook):
            return Agent.from_config(config, confirm_hook=confirm_hook, persist_memory=False)

        try:
            TelegramBot(config, telegram_agent).run()
        except ValueError as exc:
            _print(f"Telegram error: {exc}", style="red")
            return 1
        return 0

    try:
        agent, config = build_agent(args)
    except (ValueError, ImportError) as exc:
        _print(f"Configuration error: {exc}", style="red")
        return 1

    if args.list_tools:
        _print(agent.tools.describe())
        return 0

    if args.gui:
        from .ui import AssistantWindow

        voice = None
        if config.voice.enabled:
            from .voice import VoiceIO

            voice = VoiceIO(config.voice)
        window = AssistantWindow(
            agent, voice=voice, stream=getattr(config.interface, "stream", False)
        )
        agent.confirm_hook = window.confirm
        agent.on_event = lambda line: window.push_event("trace", line)
        window.run()
        return 0

    voice = None
    if config.voice.enabled:
        from .voice import VoiceIO

        voice = VoiceIO(config.voice)

    if args.message:
        return run_once(agent, args.message, config)
    return run_repl(agent, voice=voice, config=config)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
