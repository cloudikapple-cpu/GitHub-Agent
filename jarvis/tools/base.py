"""Tool abstraction and registry.

A tool is a small, self-describing capability: a name, a description, a JSON
Schema for its arguments, and a ``run`` method. The registry converts them into
the function-calling schema every supported LLM backend understands.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Iterator


class Tool(ABC):
    """Base class for all tools."""

    #: Unique tool name exposed to the model.
    name: str = ""
    #: One or two sentences telling the model when to use this tool.
    description: str = ""
    #: JSON Schema describing the arguments.
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    #: Ask the user before running (destructive or sensitive actions).
    requires_confirmation: bool = False
    #: Grouping used by ``jarvis --list-tools`` and the UI.
    category: str = "general"

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:
        """Execute the tool and return a result (str or JSON-serialisable)."""

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class FunctionTool(Tool):
    """Wrap a plain Python callable as a tool — the basis of user skills."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        func: Callable[..., Any],
        requires_confirmation: bool = False,
        category: str = "skill",
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.func = func
        self.requires_confirmation = requires_confirmation
        self.category = category

    def run(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)


class ToolRegistry:
    """A name -> tool mapping with safe execution."""

    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    # ------------------------------------------------------------------
    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tools must define a name.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def describe(self) -> str:
        """Human-readable listing grouped by category."""

        groups: dict[str, list[Tool]] = {}
        for tool in self._tools.values():
            groups.setdefault(tool.category, []).append(tool)
        lines = []
        for category in sorted(groups):
            lines.append(f"\n{category}:")
            for tool in sorted(groups[category], key=lambda t: t.name):
                flag = " (confirm)" if tool.requires_confirmation else ""
                lines.append(f"  {tool.name}{flag} — {tool.description.splitlines()[0]}")
        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'."
        try:
            result = tool.run(**arguments)
        except TypeError as exc:
            return f"Error: invalid arguments for '{name}': {exc}"
        except Exception as exc:  # noqa: BLE001 - tool errors go back to the model
            return f"Error while running '{name}': {exc}"
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(result)
