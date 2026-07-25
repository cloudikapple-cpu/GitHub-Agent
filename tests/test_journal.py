"""The undo journal must be able to reverse every destructive file action."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.journal import Journal
from jarvis.security import SecurityPolicy
from jarvis.tools.files import DeletePathTool, MovePathTool, WriteFileTool
from jarvis.tools.undo import HistoryTool, UndoTool


def _journal(tmp_path: Path) -> Journal:
    return Journal(path=tmp_path / "journal.jsonl", trash=tmp_path / "trash")


def test_undo_restores_an_overwritten_file(tmp_path):
    journal = _journal(tmp_path)
    target = tmp_path / "notes.txt"
    target.write_text("original", encoding="utf-8")

    WriteFileTool(SecurityPolicy(), journal).run(path=str(target), content="replaced")
    assert target.read_text(encoding="utf-8") == "replaced"

    UndoTool(journal).run()
    assert target.read_text(encoding="utf-8") == "original"


def test_undo_removes_a_newly_created_file(tmp_path):
    journal = _journal(tmp_path)
    target = tmp_path / "fresh.txt"

    WriteFileTool(SecurityPolicy(), journal).run(path=str(target), content="hello")
    assert target.is_file()

    UndoTool(journal).run()
    assert not target.exists()


def test_delete_is_recoverable(tmp_path):
    journal = _journal(tmp_path)
    target = tmp_path / "keep.txt"
    target.write_text("precious", encoding="utf-8")

    DeletePathTool(SecurityPolicy(), journal).run(path=str(target))
    assert not target.exists()

    UndoTool(journal).run()
    assert target.read_text(encoding="utf-8") == "precious"


def test_undo_reverses_a_move(tmp_path):
    journal = _journal(tmp_path)
    source = tmp_path / "a.txt"
    destination = tmp_path / "sub" / "b.txt"
    source.write_text("data", encoding="utf-8")

    MovePathTool(SecurityPolicy(), journal).run(
        source=str(source), destination=str(destination)
    )
    assert destination.is_file()
    assert not source.exists()

    UndoTool(journal).run()
    assert source.read_text(encoding="utf-8") == "data"
    assert not destination.exists()


def test_undo_on_an_empty_journal_is_harmless(tmp_path):
    assert "Nothing to undo" in UndoTool(_journal(tmp_path)).run()


def test_history_lists_the_newest_action_first(tmp_path):
    journal = _journal(tmp_path)
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"

    WriteFileTool(SecurityPolicy(), journal).run(path=str(first), content="1")
    WriteFileTool(SecurityPolicy(), journal).run(path=str(second), content="2")

    listing = HistoryTool(journal).run()
    assert listing.index("two.txt") < listing.index("one.txt")
