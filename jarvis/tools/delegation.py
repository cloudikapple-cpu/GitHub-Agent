"""Delegate a self-contained subtask to a fresh assistant instance.

The sub-agent gets its own short conversation, so long research or refactoring
jobs do not pollute the main context window. It is also the cheap half of the
\"local model + cloud model\" setup: routine subtasks can run on the local
provider while the main loop keeps the strong one.
"""

from __future__ import annotations

from typing import Any, Callable

from .base import Tool


class DelegateTool(Tool):
    name = "delegate"
    description = (
        "Hand a self-contained subtask to a helper agent and get back only its "
        "final answer. Use it for long research, bulk file work or anything "
        "that would flood the conversation with intermediate steps."
    )
    category = "agents"
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Full, self-contained instruction — the helper sees no history.",
            },
            "provider": {
                "type": "string",
                "description": "Optional provider name, e.g. 'ollama' for a cheap local run.",
            },
        },
        "required": ["task"],
    }

    #: Guard against a helper spawning helpers forever.
    max_depth = 2

    def __init__(self, agent_factory: Callable[[str | None], Any], depth: int = 0) -> None:
        self._agent_factory = agent_factory
        self.depth = depth

    def run(self, task: str, provider: str = "") -> str:
        if self.depth >= self.max_depth:
            return "Error: delegation depth limit reached; do this task directly."
        try:
            agent = self._agent_factory(provider or None)
        except Exception as exc:  # noqa: BLE001 - report config errors to the model
            return f"Error: cannot start helper agent: {exc}"
        result = agent.run(task)
        return str(result).strip() or "(the helper returned nothing)"
