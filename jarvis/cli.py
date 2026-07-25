"""Command line interface: one-shot, REPL, GUI, web, daemon and Telegram modes."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from .agent import Agent
from .config import SOURCE_CLI, Config

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
        config.mark_source(attribute, SOURCE_CLI)
    return config


def apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    """Apply command-line overrides to a loaded config.

    Every change is recorded as coming from the command line, so
    ``jarvis --doctor`` can explain which setting won and why.
    """

    def override(key: str, value: Any, *targets: Any) -> None:
        target, attribute = (targets or (config, key))[0], key.rsplit(".", 1)[-1]
        setattr(target, attribute, value)
        config.mark_source(key, SOURCE_CLI)

    # The profile goes first so individual flags can still override it.
    if getattr(args, "profile", None):
        apply_profile(config, args.profile)

    if args.backend:
        override("backend", args.backend)
        override("router.enabled", False, config.router)
    if args.model:
        config.provider().model = args.model
        config.mark_source(f"providers.{config.provider().name}.model", SOURCE_CLI)
    if args.api_base:
        config.provider().base_url = args.api_base
        config.mark_source(f"providers.{config.provider().name}.base_url", SOURCE_CLI)
    if args.api_key:
        config.provider().api_key = args.api_key
        config.mark_source(f"providers.{config.provider().name}.api_key", SOURCE_CLI)
    if args.router:
        override("router.enabled", True, config.router)
    if args.no_router:
        override("router.enabled", False, config.router)
    if args.no_confirm:
        override("require_confirmation", False)
    if args.yolo:
        apply_profile(config, "yolo")
    if args.dry_run:
        override("dry_run", True)
    if args.voice:
        override("voice.enabled", True, config.voice)
    if args.sandbox:
        override("execution_sandbox.mode", args.sandbox, config.execution_sandbox)
    if getattr(args, "stream", False):
        override("interface.stream", True, config.interface)
    if getattr(args, "no_stream", False):
        override("interface.stream", False, config.interface)

    # -- 0.6.0 switches --
    if getattr(args, "no_cache", False):
        override("cache.enabled", False, config.cache)
    if getattr(args, "rag", False):
        override("rag.enabled", True, config.rag)
    if getattr(args, "no_rag", False):
        override("rag.enabled", False, config.rag)
    if getattr(args, "plan", False):
        override("planner.enabled", True, config.planner)
    if getattr(args, "no_plan", False):
        override("planner.enabled", False, config.planner)
    if getattr(args, "web", False):
        override("web.enabled", True, config.web)
    if getattr(args, "web_host", None):
        override("web.host", args.web_host, config.web)
    if getattr(args, "web_port", None):
        override("web.port", int(args.web_port), config.web)
    if getattr(args, "hotkey", None):
        override("interface.hotkey", args.hotkey, config.interface)
    if getattr(args, "voice_hotkey", None):
        override("interface.voice_hotkey", args.voice_hotkey, config.interface)
    return config


def build_agent(args: argparse.Namespace) -> tuple[Agent, Config]:
    config = apply_overrides(Config.load(args.config), args)
    agent = Agent.from_config(
        config,
        confirm_hook=_confirm,
        on_event=_make_event_hook(args.verbose),
    )
    return agent, config


def run_doctor(args: argparse.Namespace) -> int:
    """Print the preflight report; return 1 when something blocks the run."""

    from .doctor import diagnose, format_report, has_failures

    config = apply_overrides(Config.load(args.config), args)
    checks = diagnose(config, config_path=args.config)
    _print(format_report(checks))
    return 1 if has_failures(checks) else 0


# ----------------------------------------------------------------------
def store_secret(name: str) -> int:
    """Read a secret without echoing it and put it in the OS keychain."""

    from getpass import getpass

    from . import secrets as keychain

    if not keychain.available():
        _print(
            "No OS keychain is available. Install it with `pip install keyring`.",
            style="red",
        )
        return 1
    try:
        value = getpass(f"Value for {name} (input is hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        _print("\nCancelled.", style="dim")
        return 1
    if not value:
        _print("Nothing entered; nothing stored.", style="yellow")
        return 1
    if not keychain.set_secret(name, value):
        _print("The keychain refused to store the value.", style="red")
        return 1
    _print(f"Stored in {keychain.backend_name()}.")
    _print(f"Use it in config.yaml as:  api_key: keyring:{name}", style="dim")
    return 0


def clear_cache(args: argparse.Namespace) -> int:
    from .cache import ResponseCache

    config = Config.load(args.config)
    cache = ResponseCache(path=config.cache.path, ttl=config.cache.ttl_seconds)
    removed = cache.clear()
    cache.close()
    _print(f"Cleared {removed} cached replies.")
    return 0


def run_index(args: argparse.Namespace) -> int:
    """Index documents for retrieval."""

    from .knowledge import build_embedder
    from .rag import DocumentIndex

    config = apply_overrides(Config.load(args.config), args)
    roots = [args.index] if args.index else list(config.rag.roots)
    if not roots:
        _print(
            "Nothing to index. Pass a path (jarvis --index ~/notes) "
            "or list folders under 'rag.roots' in config.yaml.",
            style="yellow",
        )
        return 1

    index = DocumentIndex(
        path=config.rag.path,
        embedder=build_embedder(config),
        chunk_size=config.rag.chunk_size,
        overlap=config.rag.overlap,
        top_k=config.rag.top_k,
    )
    files = chunks = 0
    for root in roots:
        _print(f"Indexing {root} …", style="dim")
        report = index.index_path(root)
        files += report["files"]
        chunks += report["chunks"]
    stats = index.stats()
    index.close()
    _print(f"Indexed {files} files ({chunks} new passages).")
    _print(
        f"The index now holds {stats['chunks']} passages from {stats['files']} files.",
        style="dim",
    )
    if not config.rag.enabled:
        _print("Set 'rag.enabled: true' in config.yaml to use it in answers.", style="yellow")
    return 0


def serve_web(agent: Agent, config: Config) -> int:
    """Run the browser interface until interrupted."""

    from .webui import WebServer

    server = WebServer(
        agent,
        host=config.web.host,
        port=config.web.port,
        token=config.web.token,
        stream=getattr(config.interface, "stream", True),
    )
    url = server.start()
    _print(f"Web interface: {url}")
    _print(
        "Anything that can reach this address can run commands as you. Ctrl+C to stop.",
        style="yellow",
    )
    if config.web.open_browser:
        server.open_in_browser()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _print("\nBye.")
    finally:
        server.stop()
    return 0


# ----------------------------------------------------------------------
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
        if user_input.lower() in {"cache", ":cache"}:
            if agent.cache is None:
                _print("The reply cache is off.", style="dim")
            else:
                _print(agent.cache.stats().format())
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

    # -- reply cache --
    parser.add_argument(
        "--no-cache", action="store_true", help="Do not reuse cached answers for this run."
    )
    parser.add_argument(
        "--clear-cache", action="store_true", help="Delete every cached answer and exit."
    )

    # -- documents --
    parser.add_argument(
        "--index",
        nargs="?",
        const="",
        metavar="PATH",
        help="Index a file or folder for retrieval (no PATH: use rag.roots), then exit.",
    )
    parser.add_argument("--rag", action="store_true", help="Use indexed documents in answers.")
    parser.add_argument("--no-rag", action="store_true", help="Ignore indexed documents.")

    # -- planner --
    parser.add_argument(
        "--plan", action="store_true", help="Draft a plan before acting on long requests."
    )
    parser.add_argument("--no-plan", action="store_true", help="Skip the planning step.")

    # -- interfaces --
    parser.add_argument("--voice", action="store_true", help="Use the microphone for input.")
    parser.add_argument("--gui", action="store_true", help="Open the desktop window.")
    parser.add_argument(
        "--web", action="store_true", help="Serve the browser interface and stay running."
    )
    parser.add_argument("--web-host", help="Address the web interface binds to (default 127.0.0.1).")
    parser.add_argument("--web-port", type=int, help="Port for the web interface (default 8765).")
    parser.add_argument("--hotkey", help="Global shortcut that opens the window, e.g. alt+shift+space.")
    parser.add_argument("--voice-hotkey", help="Global shortcut that starts voice capture.")
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

    # -- diagnostics --
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check this machine for everything Jarvis needs, then exit.",
    )
    parser.add_argument(
        "--usage",
        nargs="?",
        const="today",
        metavar="DAY",
        help="Print token and spend accounting for today (or for YYYY-MM-DD) and exit.",
    )
    parser.add_argument(
        "--set-secret",
        metavar="NAME",
        help="Store a secret in the OS keychain, then use it as keyring:NAME.",
    )
    parser.add_argument("--list-tools", action="store_true", help="Print available tools and exit.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show tool calls and results.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.doctor:
        # Diagnostics run before anything is constructed: the whole point is to
        # explain a machine that cannot build an agent yet.
        return run_doctor(args)

    if args.set_secret:
        # Nothing else is needed to write to the keychain, not even a config.
        return store_secret(args.set_secret)

    if args.usage:
        # Accounting is read straight from the ledger: no provider, no API key
        # and no config file are needed to answer 'what did today cost?'.
        from .budget import default_tracker

        day = None if args.usage == "today" else args.usage
        _print(default_tracker().report(day))
        return 0

    if args.clear_cache:
        return clear_cache(args)

    if args.index is not None:
        return run_index(args)

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
        _print("Run 'jarvis --doctor' for a full check of this machine.", style="dim")
        return 1

    if args.list_tools:
        _print(agent.tools.describe())
        return 0

    if config.web.enabled:
        return serve_web(agent, config)

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
