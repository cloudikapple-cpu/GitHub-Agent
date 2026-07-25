"""Conversation memory with optional persistence to disk.

Two budgets are enforced so long sessions never blow up the context window:

* ``max_messages`` - hard cap on the number of stored turns;
* ``max_chars``    - rough proxy for a token budget.

Trimming never leaves an orphaned ``tool`` result at the start of the window,
which would make most providers reject the request. What falls out of the
window is not lost silently: a compact note about the dropped turns is kept
next to the system prompt, so the model still knows the session had a past.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .llm.base import ToolCall

#: How much of a dropped user message is quoted in the summary.
QUOTE_CHARS = 160
#: How many distinct tool names the summary lists.
MAX_SUMMARISED_TOOLS = 8


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
        compact: bool = True,
    ):
        self.system_prompt = system_prompt
        self.max_messages = max_messages
        self.max_chars = max_chars
        self.compact = compact
        self.path = Path(path).expanduser() if path else None
        self._messages: list[dict[str, Any]] = []
        self._dropped = 0
        self._dropped_tools: list[str] = []
        self._first_request = ""
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
        """Full message list: system prompt, the trim summary, then the window."""

        head: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        summary = self.summary()
        if summary:
            head.append({"role": "system", "content": summary})
        return [*head, *self._messages]

    def summary(self) -> str:
        """One-paragraph description of everything trimmed so far."""

        if not self.compact or not self._dropped:
            return ""
        parts = [
            f"Earlier in this session {self._dropped} messages were trimmed to fit "
            "the context window."
        ]
        if self._first_request:
            parts.append(f'The session started with: "{self._first_request}".')
        if self._dropped_tools:
            parts.append("Tools already used: " + ", ".join(self._dropped_tools) + ".")
        parts.append("Ask the user again if you need any of those details.")
        return " ".join(parts)

    def reset(self) -> None:
        self._messages.clear()
        self._dropped = 0
        self._dropped_tools = []
        self._first_request = ""
        self.save()

    # ------------------------------------------------------------------
    def _size(self) -> int:
        return sum(len(str(m.get("content") or "")) for m in self._messages)

    def _absorb(self, dropped: list[dict[str, Any]]) -> None:
        """Fold the messages leaving the window into the running summary."""

        if not self.compact or not dropped:
            return
        self._dropped += len(dropped)
        for message in dropped:
            if message.get("role") == "user" and not self._first_request:
                text = " ".join(str(message.get("content") or "").split())
                self._first_request = text[:QUOTE_CHARS]
            for call in message.get("tool_calls") or []:
                name = getattr(call, "name", "")
                if name and name not in self._dropped_tools:
                    if len(self._dropped_tools) < MAX_SUMMARISED_TOOLS:
                        self._dropped_tools.append(name)

    def _drop_from_front(self, count: int) -> None:
        overflow = count
        while overflow < len(self._messages) and self._messages[overflow]["role"] == "tool":
            overflow += 1
        self._absorb(self._messages[:overflow])
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
            payload = {
                "messages": [_encode(m) for m in self._messages],
                "trimmed": {
                    "count": self._dropped,
                    "tools": self._dropped_tools,
                    "first_request": self._first_request,
                },
            }
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
        trimmed = data.get("trimmed") or {}
        self._dropped = int(trimmed.get("count", 0) or 0)
        self._dropped_tools = list(trimmed.get("tools") or [])
        self._first_request = str(trimmed.get("first_request") or "")
        self._trim()
