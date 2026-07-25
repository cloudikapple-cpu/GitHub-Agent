"""Context protection: capped tool output and summarised trimming."""

from __future__ import annotations

from jarvis.memory import ConversationMemory
from jarvis.tools.base import FunctionTool, ToolRegistry, truncate_result

EMPTY_SCHEMA = {"type": "object", "properties": {}}


def test_truncation_keeps_the_head_and_the_tail():
    text = "A" * 500 + "TAIL"
    out = truncate_result(text, limit=100)
    assert out.startswith("A")
    assert out.endswith("TAIL")
    assert "cut from the middle" in out
    assert len(out) < len(text)


def test_short_results_pass_through_unchanged():
    assert truncate_result("short", limit=100) == "short"
    assert truncate_result("x" * 50, limit=0) == "x" * 50


def test_the_registry_caps_a_chatty_tool():
    tool = FunctionTool("big", "returns a lot", EMPTY_SCHEMA, lambda: "x" * 5000)
    registry = ToolRegistry([tool], result_limit=200)
    assert len(registry.execute("big", {})) < 500


def test_memory_summarises_what_it_trims():
    memory = ConversationMemory("sys", max_messages=4, max_chars=0)
    memory.add({"role": "user", "content": "index my photos"})
    for step in range(6):
        memory.add({"role": "assistant", "content": f"step {step}"})

    summary = memory.summary()
    assert "trimmed" in summary
    assert "index my photos" in summary
    assert memory.messages()[1]["content"] == summary
    assert memory.messages()[0]["role"] == "system"


def test_no_summary_before_anything_is_trimmed():
    memory = ConversationMemory("sys", max_messages=10, max_chars=0)
    memory.add({"role": "user", "content": "hello"})
    assert memory.summary() == ""
    assert len(memory.messages()) == 2


def test_reset_clears_the_summary():
    memory = ConversationMemory("sys", max_messages=1, max_chars=0)
    memory.add({"role": "user", "content": "hello"})
    memory.add({"role": "user", "content": "again"})
    assert memory.summary()
    memory.reset()
    assert memory.summary() == ""
    assert len(memory.messages()) == 1
