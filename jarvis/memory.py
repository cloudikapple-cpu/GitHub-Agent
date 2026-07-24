"""Conversation memory with optional persistence to disk.

Two budgets are enforced so long sessions never blow up the context window:

* ``max_messages`` — hard cap on the number of stored turns;
* ``max_chars``    — rough proxy for a token budget.

Trimming never leaves an orphaned ``tool`` result at the start of the window,
which would make most providers reject the request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .llm.base import ToolCall


def _encode(message: dict[str, Any]) -> dict[str, Any]:
    out = dict(message)
    calls = out.get("tool_calls")
    if calls:
        out["tool_calls"] = [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in calls
        ]
    return out


def _decode(message: dict[str, Any]) -> dict[str, Any]:
    out = dict(message)
    calls = out.get("tool_calls")
    if calls:
        out["tool_calls"] = [
            ToolCall(id=c.get("id", ""), name=c.get("name", ""), arguments=c.get("arguments") or {})
            for c in calls
        ]
    return out


class ConversationMemory:
    """Running message list plus optional JSON persistence."""

    def __init__(
        self,
        system_prompt: str,
        max_messages: int = 40,
        max_chars: int = 24000,
        path: str | None = None,
    ):
        self.system_prompt = system_prompt
        self.max_messages = max_messages
        self.max_chars = max_chars
        self.path = Path(path).expanduser() if path else None
        self._messages: list[dict[str, Any]] = []
        if self.path is not None:
            self.load()

    # ------------------------------------------------------------------
    def add(self, message: dict[str, Any]) -> None:
        self._messages.append(message)
        self._trim()
        self.save()

    def extend(self, messages: list[dict[str, Any]]) -> None:
        self._messages.extend(messages)
        self._trim()
        self.save()

    def messages(self) -> list[dict[str, Any]]:
        """Full message list including the system prompt."""

        return [{"role": "system", "content": self.system_prompt}, *self._messages]

    def reset(self) -> None:
        self._messages.clear()
        self.save()

    # ------------------------------------------------------------------
    def _size(self) -> int:
        return sum(len(str(m.get("content") or "")) for m in self._messages)

    def _drop_from_front(self, count: int) -> None:
        overflow = count
        while overflow < len(self._messages) and self._messages[overflow]["role"] == "tool":
            overflow += 1
        self._messages = self._messages[overflow:]

    def _trim(self) -> None:
        if len(self._messages) > self.max_messages:
            self._drop_from_front(len(self._messages) - self.max_messages)
        while self.max_chars and self._size() > self.max_chars and len(self._messages) > 2:
            self._drop_from_front(1)

    # ------------------------------------------------------------------
    def save(self) -> None:
        """Persist the conversation (best effort)."""

        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"messages": [_encode(m) for m in self._messages]}
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:  # pragma: no cover - persistence must never break a run
            pass

    def load(self) -> None:
        """Restore a previously persisted conversation (best effort)."""

        if self.path is None or not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # pragma: no cover
            return
        self._messages = [_decode(m) for m in data.get("messages", [])]
        self._trim()
