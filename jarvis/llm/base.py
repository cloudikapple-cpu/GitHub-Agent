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

Streaming has two entry points. :meth:`LLMBackend.stream_response` is the one
backends implement: it pushes text into a ``sink`` callback as it arrives and
returns the complete response, tool calls included -- which is what an agent
loop needs. :meth:`LLMBackend.stream` is the convenience generator built on top
of it for callers that only want text.
"""

from __future__ import annotations

import queue
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
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
    #: True when the provider said nothing at all and ``content`` is only an
    #: explanation of that silence. The router uses it to try someone else.
    empty: bool = False
    #: True when the answer was replayed from the local cache.
    cached: bool = False

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMBackend(ABC):
    """Abstract base class every backend implements."""

    name: str = "base"
    #: Backends that can read images set this to ``True``.
    supports_vision: bool = False
    #: Backends that override :meth:`stream_response` set this to ``True``.
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
    def stream_response(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        sink: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Stream the reply into ``sink`` and return the complete response.

        The default implementation performs a normal request and hands over the
        whole answer at once, so every backend works with streaming callers --
        just without the typewriter effect.
        """

        response = self.chat(messages, tools)
        if sink is not None and response.content and not response.wants_tools:
            sink(response.content)
        return response

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[str]:
        """Yield the reply in chunks as they arrive.

        The producer runs on its own thread so chunks reach the caller while
        the request is still open; failures are re-raised on the caller's side.
        """

        chunks: queue.Queue[str | None] = queue.Queue()
        failure: dict[str, Exception] = {}

        def worker() -> None:
            try:
                self.stream_response(messages, tools, sink=chunks.put)
            except Exception as exc:  # noqa: BLE001 - re-raised on the consumer side
                failure["error"] = exc
            finally:
                chunks.put(None)

        thread = threading.Thread(target=worker, name="jarvis-llm-stream", daemon=True)
        thread.start()
        while True:
            item = chunks.get()
            if item is None:
                break
            yield item
        thread.join(timeout=5)
        if "error" in failure:
            raise failure["error"]
