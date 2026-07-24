"""The core agent: an LLM reasoning loop wired to a set of tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .config import Config
from .llm import LLMBackend, build_backend
from .llm.base import ToolCall
from .memory import ConversationMemory
from .tools import ToolRegistry, build_default_registry

DEFAULT_SYSTEM_PROMPT = """You are Jarvis, a capable desktop AI assistant.

You help the user accomplish real tasks on their computer. You can search the
web, read and write files, run shell commands and Python, open applications and
URLs, and control the keyboard/mouse when needed.

Guidelines:
- Think step by step and use tools to gather information instead of guessing.
- Prefer the least intrusive action that accomplishes the goal.
- When a task needs several steps, do them one at a time and check the results.
- Be concise. Report what you did and the outcome.
- If an action could be destructive or irreversible, explain it clearly first.
"""

# Hook type: (tool_name, arguments) -> approved?
ConfirmHook = Callable[[str, dict[str, Any]], bool]
# Hook type: called with a human-readable trace line.
EventHook = Callable[[str], None]


@dataclass
class AgentEvent:
    """Emitted as the agent works, for UIs that want to show progress."""

    kind: str  # "tool_call" | "tool_result" | "final"
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
    ):
        self.backend = backend
        self.tools = tools
        self.max_iterations = max_iterations
        self.require_confirmation = require_confirmation
        self.confirm_hook = confirm_hook
        self.on_event = on_event
        self.memory = ConversationMemory(system_prompt)

    # ------------------------------------------------------------------
    @classmethod
    def from_config(
        cls,
        config: Config,
        confirm_hook: ConfirmHook | None = None,
        on_event: EventHook | None = None,
    ) -> "Agent":
        backend = build_backend(config)
        tools = build_default_registry(config)
        system_prompt = DEFAULT_SYSTEM_PROMPT
        if config.persona:
            system_prompt = f"{system_prompt}\n\nPersona:\n{config.persona.strip()}"
        return cls(
            backend=backend,
            tools=tools,
            system_prompt=system_prompt,
            max_iterations=config.max_iterations,
            require_confirmation=config.require_confirmation,
            confirm_hook=confirm_hook,
            on_event=on_event,
        )

    # ------------------------------------------------------------------
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
        if self._needs_confirmation(call.name):
            approved = self.confirm_hook(call.name, call.arguments)  # type: ignore[misc]
            if not approved:
                return "The user declined to run this action."
        result = self.tools.execute(call.name, call.arguments)
        self._emit("tool_result", result[:500])
        return result

    # ------------------------------------------------------------------
    def run(self, user_message: str) -> str:
        """Process a single user message and return the assistant's final reply."""

        self.memory.add({"role": "user", "content": user_message})
        tool_schemas = self.tools.schemas()

        for _ in range(self.max_iterations):
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
                result = self._run_tool_call(call)
                self.memory.add(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": result,
                    }
                )

        message = "Stopped after reaching the maximum number of tool iterations."
        self.memory.add({"role": "assistant", "content": message})
        return message
