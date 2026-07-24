"""Tools for the long-term semantic memory."""

from __future__ import annotations

from typing import Any

from ..knowledge import KnowledgeBase
from .base import Tool


class RememberTool(Tool):
    name = "remember"
    description = (
        "Store a durable fact, preference or decision in long-term memory. "
        "Use it when the user shares something worth recalling in future sessions."
    )
    category = "memory"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The fact to remember, self-contained."},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional labels, e.g. ['work', 'preferences'].",
            },
        },
        "required": ["text"],
    }

    def __init__(self, knowledge: KnowledgeBase) -> None:
        self.knowledge = knowledge

    def run(self, text: str, tags: list[str] | None = None) -> str:
        note_id = self.knowledge.add(text, tags=tags, source="assistant")
        return f"Remembered as note #{note_id}."


class RecallTool(Tool):
    name = "recall"
    description = (
        "Search long-term memory by meaning. Use it before answering questions "
        "about the user, past decisions or previous sessions."
    )
    category = "memory"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for."},
            "limit": {"type": "integer", "description": "How many notes to return."},
            "tag": {"type": "string", "description": "Restrict the search to one tag."},
        },
        "required": ["query"],
    }

    def __init__(self, knowledge: KnowledgeBase) -> None:
        self.knowledge = knowledge

    def run(self, query: str, limit: int | None = None, tag: str = "") -> str:
        notes = self.knowledge.search(query, limit=limit, tag=tag)
        if not notes:
            return "Nothing relevant in long-term memory."
        return "\n".join(note.format() for note in notes)


class ForgetTool(Tool):
    name = "forget"
    description = "Delete a note from long-term memory by its id (from recall)."
    category = "memory"
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {"note_id": {"type": "integer", "description": "Note id to delete."}},
        "required": ["note_id"],
    }

    def __init__(self, knowledge: KnowledgeBase) -> None:
        self.knowledge = knowledge

    def run(self, note_id: int) -> str:
        return (
            f"Note #{note_id} deleted."
            if self.knowledge.forget(int(note_id))
            else f"No note #{note_id}."
        )


def build_knowledge_tools(knowledge: KnowledgeBase) -> list[Any]:
    return [RememberTool(knowledge), RecallTool(knowledge), ForgetTool(knowledge)]
