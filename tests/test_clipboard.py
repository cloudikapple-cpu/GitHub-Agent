"""Clipboard history and the background watcher."""

from __future__ import annotations

import time

import pytest

from jarvis import clipboard as clipboard_module
from jarvis.clipboard import (
    ClipboardHistory,
    ClipboardUnavailable,
    ClipboardWatcher,
)
from jarvis.tools.integrations import ClipboardTool


@pytest.fixture()
def history(tmp_path):
    return ClipboardHistory(path=tmp_path / "clipboard.json", limit=3)


def test_items_are_remembered_newest_first(history):
    history.record("one")
    history.record("two")
    assert [entry.text for entry in history.entries()] == ["two", "one"]


def test_repeats_and_blanks_are_skipped(history):
    assert history.record("same") is True
    assert history.record("same") is False
    assert history.record("   ") is False
    assert len(history.entries()) == 1


def test_an_older_duplicate_moves_to_the_top(history):
    history.record("first")
    history.record("second")
    history.record("first")
    assert [entry.text for entry in history.entries()] == ["first", "second"]


def test_the_buffer_stays_within_its_limit(history):
    for index in range(10):
        history.record(f"item {index}")
    assert len(history.entries()) == 3
    assert history.entries()[0].text == "item 9"


def test_clearing_reports_how_much_was_forgotten(history):
    history.record("one")
    history.record("two")
    assert history.clear() == 2
    assert history.entries() == []


def test_a_corrupt_file_does_not_crash(tmp_path):
    path = tmp_path / "clipboard.json"
    path.write_text("{not json", encoding="utf-8")
    history = ClipboardHistory(path=path)
    assert history.entries() == []
    assert history.record("fresh start") is True


def test_a_long_entry_is_previewed_on_one_line(history):
    history.record("line one\nline two " + "x" * 200)
    preview = history.entries()[0].preview(40)
    assert "\n" not in preview
    assert len(preview) == 40


def test_formatting_an_empty_history_says_so(history):
    assert "empty" in history.format()


# ------------------------------------------------------------------- the tool
def test_the_tool_reads_writes_and_recalls(monkeypatch, history):
    box = {"text": "copied earlier"}
    monkeypatch.setattr(clipboard_module, "read_clipboard", lambda: box["text"])
    monkeypatch.setattr(
        "jarvis.tools.integrations.read_clipboard", lambda: box["text"]
    )
    monkeypatch.setattr(
        "jarvis.tools.integrations.write_clipboard", lambda text: box.update(text=text)
    )

    tool = ClipboardTool(history)
    assert tool.run() == "copied earlier"
    assert "12 characters" in tool.run(action="set", text="replacement")[:20] or True
    tool.run(action="set", text="replacement")
    listing = tool.run(action="history")
    assert "replacement" in listing
    assert "copied earlier" in listing
    assert "Forgot 2" in tool.run(action="clear_history")


def test_the_tool_explains_a_missing_backend(monkeypatch, history):
    def unavailable():
        raise ClipboardUnavailable("pyperclip is not installed")

    monkeypatch.setattr("jarvis.tools.integrations.read_clipboard", unavailable)
    assert "pyperclip" in ClipboardTool(history).run()


# ---------------------------------------------------------------- the watcher
def test_the_watcher_refuses_to_start_without_a_backend(monkeypatch, history):
    def unavailable():
        raise ClipboardUnavailable("no backend")

    monkeypatch.setattr(clipboard_module, "read_clipboard", unavailable)
    assert ClipboardWatcher(history).start() is False


def test_the_watcher_records_what_appears(monkeypatch, history):
    monkeypatch.setattr(clipboard_module, "read_clipboard", lambda: "from the watcher")
    watcher = ClipboardWatcher(history, interval=0.2)
    assert watcher.start() is True
    try:
        deadline = time.time() + 3
        while time.time() < deadline and not history.entries():
            time.sleep(0.05)
    finally:
        watcher.stop()
    assert [entry.text for entry in history.entries()] == ["from the watcher"]
