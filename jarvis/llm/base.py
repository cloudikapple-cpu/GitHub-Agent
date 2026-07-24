"""Common types and interface shared by every LLM backend.

Backends translate the *normalised* message/tool format used throughout Jarvis
into whatever the underlying provider expects, and translate the response back
into an :class:`LLMResponse`.

Normalised message shapes (plain ``dict``s):

* ``{"role": "system",    "content": str}``
* ``{"role": "user",      "content": str}``
* ``{"role": "assistant", "content": str}``
* ``{"role": "assistant", "content": str | None, "tool_calls": [ToolCall, ...]}``
* ``{"role": "tool",      "tool_call_id": str, "name": str, "content": str}``
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A request from the model to invoke a tool."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """A normalised response from a backend."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMBackend(ABC):
    """Abstract base class every backend implements."""

    name: str = "base"

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send ``messages`` (and optional ``tools`` schemas) and return a response."""
        raise NotImplementedError
