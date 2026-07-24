from pathlib import Path

from jarvis.llm.base import ToolCall
from jarvis.memory import ConversationMemory


def test_messages_include_system_prompt():
    memory = ConversationMemory("be helpful")
    memory.add({"role": "user", "content": "hi"})
    messages = memory.messages()

    assert messages[0] == {"role": "system", "content": "be helpful"}
    assert messages[1]["content"] == "hi"


def test_char_budget_trims_history():
    memory = ConversationMemory("sys", max_messages=100, max_chars=200)
    for index in range(20):
        memory.add({"role": "user", "content": "x" * 50 + str(index)})

    total = sum(len(m["content"]) for m in memory.messages()[1:])
    assert total <= 200


def test_trimming_never_starts_with_tool_message():
    memory = ConversationMemory("sys", max_messages=3)
    memory.add({"role": "user", "content": "do it"})
    memory.add({"role": "assistant", "content": None, "tool_calls": [ToolCall("1", "t", {})]})
    memory.add({"role": "tool", "tool_call_id": "1", "name": "t", "content": "done"})
    memory.add({"role": "assistant", "content": "finished"})

    assert memory.messages()[1]["role"] != "tool"


def test_persistence_round_trip(tmp_path: Path):
    path = tmp_path / "history.json"
    first = ConversationMemory("sys", path=str(path))
    first.add({"role": "user", "content": "remember this"})
    first.add({"role": "assistant", "content": None, "tool_calls": [ToolCall("1", "t", {"a": 1})]})

    second = ConversationMemory("sys", path=str(path))
    restored = second.messages()

    assert restored[1]["content"] == "remember this"
    assert restored[2]["tool_calls"][0].name == "t"

    second.reset()
    assert ConversationMemory("sys", path=str(path)).messages() == [
        {"role": "system", "content": "sys"}
    ]
