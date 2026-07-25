"""Tools exposing the undo journal to the model."""

from __future__ import annotations

from ..journal import Journal
from .base import Tool


class UndoTool(Tool):
    name = "undo_last"
    description = (
        "Undo the most recent destructive filesystem action taken by Jarvis "
        "(a delete, an overwrite or a move). Use this when the user says the "
        "last change was wrong."
    )
    requires_confirmation = True
    parameters = {"type": "object", "properties": {}}

    def __init__(self, journal: Journal | None = None):
        self.journal = journal or Journal()

    def run(self) -> str:
        return self.journal.undo_last()


class HistoryTool(Tool):
    name = "list_recent_changes"
    description = (
        "List the recent destructive filesystem actions taken by Jarvis, "
        "newest first, so the user can see what can be undone."
    )
    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many entries to show (default 10).",
                "default": 10,
            }
        },
    }

    def __init__(self, journal: Journal | None = None):
        self.journal = journal or Journal()

    def run(self, limit: int = 10) -> str:
        return self.journal.history(limit=max(1, int(limit or 10)))
