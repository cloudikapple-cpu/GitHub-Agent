"""Command-line interface for Jarvis."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .agent import Agent
from .config import Config

try:  # pretty output is optional
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel

    _console: Console | None = Console()
except ImportError:  # pragma: no cover
    _console = None


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
    _print(f"\n⚠  Jarvis wants to run [bold]{tool_name}[/bold] with:", style="yellow")
    for key, value in arguments.items():
        preview = str(value)
        if len(preview) > 300:
            preview = preview[:300] + "…"
        _print(f"    {key} = {preview}")
    try:
        answer = input("Allow this action? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _make_event_hook(verbose: bool):
    if not verbose:
        return None

    def hook(line: str) -> None:
        if line.startswith("[tool_call]"):
            _print(line, style="cyan")
        elif line.startswith("[tool_result]"):
            _print(line, style="dim")

    return hook


def build_agent(args: argparse.Namespace) -> Agent:
    config = Config.load(args.config)
    if args.backend:
        config.backend = args.backend
    if args.no_confirm:
        config.require_confirmation = False
    return Agent.from_config(
        config,
        confirm_hook=_confirm,
        on_event=_make_event_hook(args.verbose),
    )


def run_once(agent: Agent, message: str) -> None:
    reply = agent.run(message)
    _print_markdown(reply)


def run_repl(agent: Agent) -> None:
    banner = "Jarvis is ready. Type your request, or 'exit' to quit."
    if _console is not None:
        _console.print(Panel(banner, title="Jarvis", border_style="green"))
    else:
        print(banner)

    while True:
        try:
            message = input("\nyou › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not message:
            continue
        if message.lower() in {"exit", "quit", ":q"}:
            break
        if message.lower() in {"reset", "clear"}:
            agent.memory.reset()
            _print("(conversation reset)", style="dim")
            continue
        try:
            reply = agent.run(message)
        except Exception as exc:  # noqa: BLE001 - keep the REPL alive
            _print(f"Error: {exc}", style="red")
            continue
        _print("\njarvis ›", style="bold green")
        _print_markdown(reply)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="Jarvis desktop AI assistant.")
    parser.add_argument("-m", "--message", help="Run a single request and exit.")
    parser.add_argument("-b", "--backend", choices=["openai", "anthropic", "ollama"], help="Override the LLM backend.")
    parser.add_argument("-c", "--config", default="config.yaml", help="Path to a YAML config file.")
    parser.add_argument("--no-confirm", action="store_true", help="Do not ask before running actions (use with care).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show tool calls as they happen.")
    args = parser.parse_args(argv)

    try:
        agent = build_agent(args)
    except Exception as exc:  # noqa: BLE001
        _print(f"Failed to start Jarvis: {exc}", style="red")
        return 1

    if args.message:
        run_once(agent, args.message)
    else:
        run_repl(agent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
