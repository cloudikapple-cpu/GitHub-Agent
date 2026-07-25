"""Tool abstraction and registry.

A tool is a small, self-describing capability: a name, a description, a JSON
Schema for its arguments, and a ``run`` method. The registry converts them into
the function-calling schema every supported LLM backend understands.

Results are capped before they reach the model: one ``find_files`` over a large
disk or a chatty ``run_shell`` could otherwise fill the whole context window.
The limit is ``JARVIS_MAX_TOOL_RESULT`` characters (default 20000, ``0`` off).
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from typing import Any

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_RESULT_CHARS = 20_000
#: How much of the budget goes to the beginning of an oversized result.
_HEAD_RATIO = 0.7


def configured_result_limit() -> int:
    """Result cap in characters, from the environment."""

    raw = os.environ.get("JARVIS_MAX_TOOL_RESULT", "").strip()
    if not raw:
        return DEFAULT_MAX_RESULT_CHARS
    try:
        return max(0, int(raw))
    except ValueError:
        LOGGER.warning("JARVIS_MAX_TOOL_RESULT is not a number; using the default")
        return DEFAULT_MAX_RESULT_CHARS


def truncate_result(text: str, limit: int | None = None) -> str:
    """Keep the head and the tail of an oversized result, drop the middle.

    The tail matters: shell output and stack traces put the verdict last.
    """

    cap = configured_result_limit() if limit is None else max(0, limit)
    if cap == 0 or len(text) <= cap:
        return text

    head = int(cap * _HEAD_RATIO)
    tail = cap - head
    removed = len(text) - head - tail
    marker = (
        f"\n\n...[{removed} of {len(text)} characters cut from the middle; "
        "narrow the request or read the source directly]...\n\n"
    )
    return text[:head] + marker + (text[-tail:] if tail else "")


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
    """Wrap a plain Python callable as a tool - the basis of user skills."""

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

    def __init__(self, tools: list[Tool] | None = None, result_limit: int | None = None):
        self._tools: dict[str, Tool] = {}
        self.result_limit = result_limit
        for tool in tools or []:
            self.register(tool)

    # ------------------------------------------------------------------
    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tools must define a name.")
        replaced = self._tools.get(tool.name)
        if replaced is not None and type(replaced) is not type(tool):
            LOGGER.warning(
                "Tool '%s' (%s) is being replaced by %s - a skill is shadowing a built-in tool.",
                tool.name,
                type(replaced).__name__,
                type(tool).__name__,
            )
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
                lines.append(f"  {tool.name}{flag} - {tool.description.splitlines()[0]}")
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
            text = result
        else:
            try:
                text = json.dumps(result, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                text = str(result)
        return truncate_result(text, self.result_limit)
