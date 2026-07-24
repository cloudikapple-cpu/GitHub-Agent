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

A user message may also carry images for vision-capable models::

    {"role": "user", "content": "what is on my screen?",
     "images": ["<base64 png>"]}
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
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
    #: Provider that actually produced the answer (useful with the router).
    provider: str = ""

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMBackend(ABC):
    """Abstract base class every backend implements."""

    name: str = "base"
    #: Backends that can read images set this to ``True``.
    supports_vision: bool = False
    #: Backends that override :meth:`stream` set this to ``True``.
    supports_streaming: bool = False

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send ``messages`` (and optional ``tools`` schemas) and return a response."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[str]:
        """Yield the reply in chunks.

        The default implementation simply performs a normal request and yields
        the whole answer once, so every backend can be used with streaming
        interfaces without extra work.
        """

        response = self.chat(messages, tools)
        if response.content:
            yield response.content
