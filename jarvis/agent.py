"""The core agent: an LLM reasoning loop wired to a set of tools."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from .config import Config
from .llm import LLMBackend, build_backend
from .llm.base import ToolCall
from .memory import ConversationMemory
from .security import SecurityError
from .tools import ToolRegistry, build_default_registry

DEFAULT_SYSTEM_PROMPT = """You are Jarvis, a capable desktop AI assistant.

You help the user accomplish real tasks on their computer. You can search the
web, read and write files, create and delete folders, write and run code, run
shell commands, install or remove applications, call external HTTP APIs, open
programs and URLs, set reminders, remember facts for later, look at the screen,
and control the keyboard/mouse when needed.

Guidelines:
- Think step by step and use tools to gather information instead of guessing.
- Prefer the least intrusive action that accomplishes the goal.
- When a task needs several steps, do them one at a time and check the results.
- After writing code, run it or its tests to verify it actually works.
- Use `recall` when the answer may depend on earlier sessions, and `remember`
  when the user shares a durable fact, preference or decision.
- Be concise. Report what you did and the outcome.
- If an action could be destructive or irreversible, explain it clearly first.
- If a tool refuses an action for security reasons, explain why instead of
  trying to work around the restriction.
"""

DRY_RUN_NOTE = """
DRY RUN MODE: do not call any tools. Instead, reply with the numbered plan of
actions you would take, naming the exact tool and arguments for each step, and
flag anything destructive.
"""

# Hook type: (tool_name, arguments) -> approved?
ConfirmHook = Callable[[str, dict[str, Any]], bool]
# Hook type: called with a human-readable trace line.
EventHook = Callable[[str], None]


class Cancelled(RuntimeError):
    """Raised internally when the user interrupts a run."""


@dataclass
class AgentEvent:
    """Emitted as the agent works, for UIs that want to show progress."""

    kind: str  # "tool_call" | "tool_result" | "final" | "error"
    text: str


class Agent:
    def __init__(
        self,
        backend: LLMBackend,
        tools: ToolRegistry,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_iterations: int = 12,
        require_confirmation: bool = True,
        confirm_hook: ConfirmHook | None = None,
        on_event: EventHook | None = None,
        memory: ConversationMemory | None = None,
        dry_run: bool = False,
    ):
        self.backend = backend
        self.tools = tools
        self.max_iterations = max_iterations
        self.require_confirmation = require_confirmation
        self.confirm_hook = confirm_hook
        self.on_event = on_event
        self.memory = memory or ConversationMemory(system_prompt)
        self.dry_run = dry_run
        #: Set by :meth:`cancel` to stop a run between steps.
        self.cancel_event = threading.Event()

    # ------------------------------------------------------------------
    @classmethod
    def from_config(
        cls,
        config: Config,
        confirm_hook: ConfirmHook | None = None,
        on_event: EventHook | None = None,
        provider: str | None = None,
        depth: int = 0,
        persist_memory: bool = True,
    ) -> "Agent":
        backend = build_backend(config, provider)

        def backend_factory(name: str | None = None) -> LLMBackend:
            return build_backend(config, name)

        def agent_factory(name: str | None = None) -> "Agent":
            """Helper agent for the `delegate` tool: no history, no persistence."""

            return cls.from_config(
                config,
                confirm_hook=confirm_hook,
                on_event=on_event,
                provider=name,
                depth=depth + 1,
                persist_memory=False,
            )

        tools = build_default_registry(
            config,
            backend_factory=backend_factory,
            agent_factory=agent_factory if depth < 2 else None,
            depth=depth,
        )

        system_prompt = DEFAULT_SYSTEM_PROMPT
        if config.persona:
            system_prompt = f"{system_prompt}\n\nPersona:\n{config.persona.strip()}"
        if config.dry_run:
            system_prompt = f"{system_prompt}\n{DRY_RUN_NOTE}"

        memory = ConversationMemory(
            system_prompt,
            max_messages=config.memory.max_messages,
            max_chars=config.memory.max_chars,
            path=config.memory.path if (config.memory.persist and persist_memory) else None,
        )
        agent = cls(
            backend=backend,
            tools=tools,
            system_prompt=system_prompt,
            max_iterations=config.max_iterations,
            require_confirmation=config.require_confirmation,
            confirm_hook=confirm_hook,
            on_event=on_event,
            memory=memory,
            dry_run=config.dry_run,
        )
        agent.knowledge = getattr(tools, "knowledge", None)
        agent.scheduler = getattr(tools, "scheduler", None)
        return agent

    # ------------------------------------------------------------------
    def cancel(self) -> None:
        """Ask the current run to stop at the next safe point."""

        self.cancel_event.set()

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled

    def _emit(self, kind: str, text: str) -> None:
        if self.on_event:
            self.on_event(f"[{kind}] {text}")

    def _needs_confirmation(self, tool_name: str) -> bool:
        if not self.require_confirmation or self.confirm_hook is None:
            return False
        tool = self.tools.get(tool_name)
        return bool(tool and tool.requires_confirmation)

    def _run_tool_call(self, call: ToolCall) -> str:
        self._emit("tool_call", f"{call.name}({call.arguments})")
        if self.dry_run:
            return "Dry run: the action was not executed."
        if self._needs_confirmation(call.name):
            approved = self.confirm_hook(call.name, call.arguments)  # type: ignore[misc]
            if not approved:
                return "The user declined to run this action."
        try:
            result = self.tools.execute(call.name, call.arguments)
        except SecurityError as exc:
            result = f"Refused by security policy: {exc}"
        self._emit("tool_result", result[:500])
        return result

    # ------------------------------------------------------------------
    def _recall_context(self, user_message: str) -> str:
        """Pull relevant long-term notes for this message."""

        knowledge = getattr(self, "knowledge", None)
        if knowledge is None:
            return ""
        try:
            notes = [note for note in knowledge.search(user_message) if note.score > 0.15]
        except Exception:  # noqa: BLE001 - memory must never break a run
            return ""
        if not notes:
            return ""
        joined = "\n".join(f"- {note.text}" for note in notes)
        return f"Relevant notes from long-term memory:\n{joined}"

    # ------------------------------------------------------------------
    def run(self, user_message: str) -> str:
        """Process a single user message and return the assistant's final reply."""

        self.cancel_event.clear()

        context = self._recall_context(user_message)
        if context:
            self.memory.add({"role": "system", "content": context})
        self.memory.add({"role": "user", "content": user_message})
        tool_schemas = None if self.dry_run else self.tools.schemas()

        try:
            for _ in range(self.max_iterations):
                self._check_cancelled()
                response = self.backend.chat(self.memory.messages(), tools=tool_schemas)

                if not response.wants_tools:
                    final = response.content or ""
                    self.memory.add({"role": "assistant", "content": final})
                    self._emit("final", final)
                    return final

                # Record the assistant's tool-call turn, then execute each call.
                self.memory.add(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": response.tool_calls,
                    }
                )
                for call in response.tool_calls:
                    self._check_cancelled()
                    result = self._run_tool_call(call)
                    self.memory.add(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": result,
                        }
                    )
        except Cancelled:
            message = "Stopped at your request."
            self.memory.add({"role": "assistant", "content": message})
            self._emit("final", message)
            return message

        message = "Stopped after reaching the maximum number of tool iterations."
        self.memory.add({"role": "assistant", "content": message})
        return message
