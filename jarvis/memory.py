"""Very small in-memory conversation store.

Keeps the running message list and trims old turns so the context stays within
a rough budget. Persistence to disk can be layered on later.
"""

from __future__ import annotations

from typing import Any


class ConversationMemory:
    def __init__(self, system_prompt: str, max_messages: int = 40):
        self.system_prompt = system_prompt
        self.max_messages = max_messages
        self._messages: list[dict[str, Any]] = []

    def add(self, message: dict[str, Any]) -> None:
        self._messages.append(message)
        self._trim()

    def extend(self, messages: list[dict[str, Any]]) -> None:
        self._messages.extend(messages)
        self._trim()

    def messages(self) -> list[dict[str, Any]]:
        """Full message list including the system prompt."""
        return [{"role": "system", "content": self.system_prompt}, *self._messages]

    def reset(self) -> None:
        self._messages.clear()

    def _trim(self) -> None:
        if len(self._messages) <= self.max_messages:
            return
        # Drop oldest, but never start the window on an orphaned tool result.
        overflow = len(self._messages) - self.max_messages
        while overflow < len(self._messages) and self._messages[overflow]["role"] == "tool":
            overflow += 1
        self._messages = self._messages[overflow:]
