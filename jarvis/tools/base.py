"""Tool abstraction and registry.

A *tool* is a single capability the assistant can invoke. Each tool exposes a
JSON-schema description of its parameters so the LLM knows how to call it.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Callable


class Tool(ABC):
    """Base class for all tools."""

    #: Unique, snake_case identifier the model uses to call the tool.
    name: str = ""
    #: Human/LLM readable description of what the tool does and when to use it.
    description: str = ""
    #: JSON schema describing the ``run`` keyword arguments.
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    #: If True, the CLI asks the user to confirm before running (when confirmation is on).
    requires_confirmation: bool = False

    @abstractmethod
    def run(self, **kwargs: Any) -> str:
        """Execute the tool and return a string result for the model."""
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """Holds the set of tools available to an agent."""

    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError(f"Tool {tool!r} has no name.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'."
        try:
            result = tool.run(**(arguments or {}))
        except TypeError as exc:
            return f"Error: invalid arguments for '{name}': {exc}"
        except Exception as exc:  # noqa: BLE001 - surface tool errors to the model
            return f"Error while running '{name}': {exc}"
        if not isinstance(result, str):
            try:
                result = json.dumps(result, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                result = str(result)
        return result


class FunctionTool(Tool):
    """Convenience adapter to expose a plain function as a :class:`Tool`."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        func: Callable[..., Any],
        requires_confirmation: bool = False,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.requires_confirmation = requires_confirmation
        self._func = func

    def run(self, **kwargs: Any) -> str:
        return self._func(**kwargs)
