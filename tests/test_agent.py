"""Tests for the agent loop using a scripted fake backend."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.agent import Agent
from jarvis.llm.base import LLMBackend, LLMResponse, ToolCall
from jarvis.memory import ConversationMemory
from jarvis.tools.base import FunctionTool, ToolRegistry


class ScriptedBackend(LLMBackend):
    """Returns a predetermined sequence of responses."""

    name = "scripted"

    def __init__(self, responses):
        self._responses = list(responses)
        self.received_tools = None

    def chat(self, messages, tools=None):
        self.received_tools = tools
        return self._responses.pop(0)


def _registry():
    add = FunctionTool(
        name="add",
        description="add two numbers",
        parameters={
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
        func=lambda a, b: str(a + b),
    )
    return ToolRegistry([add])


def test_agent_direct_answer():
    backend = ScriptedBackend([LLMResponse(content="Hello!")])
    agent = Agent(backend, _registry(), require_confirmation=False)
    assert agent.run("hi") == "Hello!"


def test_agent_runs_tool_then_answers():
    backend = ScriptedBackend(
        [
            LLMResponse(tool_calls=[ToolCall(id="1", name="add", arguments={"a": 2, "b": 3})]),
            LLMResponse(content="The answer is 5."),
        ]
    )
    agent = Agent(backend, _registry(), require_confirmation=False)
    reply = agent.run("what is 2 + 3?")
    assert reply == "The answer is 5."
    # The tool result should have been recorded in memory.
    tool_messages = [m for m in agent.memory.messages() if m["role"] == "tool"]
    assert tool_messages and tool_messages[0]["content"] == "5"


def test_agent_confirmation_declined():
    confirmable = FunctionTool(
        name="danger",
        description="dangerous",
        parameters={"type": "object", "properties": {}},
        func=lambda: "ran",
        requires_confirmation=True,
    )
    backend = ScriptedBackend(
        [
            LLMResponse(tool_calls=[ToolCall(id="1", name="danger", arguments={})]),
            LLMResponse(content="Okay, I did not run it."),
        ]
    )
    agent = Agent(
        backend,
        ToolRegistry([confirmable]),
        require_confirmation=True,
        confirm_hook=lambda name, args: False,
    )
    agent.run("do the dangerous thing")
    tool_messages = [m for m in agent.memory.messages() if m["role"] == "tool"]
    assert "declined" in tool_messages[0]["content"]


def test_agent_hits_iteration_cap():
    # Always ask for a tool -> never terminates on its own.
    loop = [LLMResponse(tool_calls=[ToolCall(id="x", name="add", arguments={"a": 1, "b": 1})]) for _ in range(10)]
    backend = ScriptedBackend(loop)
    agent = Agent(backend, _registry(), max_iterations=3, require_confirmation=False)
    reply = agent.run("loop forever")
    assert "maximum number of tool iterations" in reply


def test_memory_trims_without_orphaning_tool_results():
    mem = ConversationMemory("system", max_messages=2)
    mem.add({"role": "user", "content": "1"})
    mem.add({"role": "assistant", "content": "2"})
    mem.add({"role": "user", "content": "3"})
    msgs = mem.messages()

    assert msgs[0] == {"role": "system", "content": "system"}
    # The dropped turn is replaced by a note rather than vanishing silently.
    assert msgs[1]["role"] == "system"
    assert "trimmed" in msgs[1]["content"]
    # system + note + the last two turns.
    assert [m["content"] for m in msgs[2:]] == ["2", "3"]


def test_memory_without_compaction_keeps_only_the_window():
    mem = ConversationMemory("system", max_messages=2, compact=False)
    mem.add({"role": "user", "content": "1"})
    mem.add({"role": "assistant", "content": "2"})
    mem.add({"role": "user", "content": "3"})
    msgs = mem.messages()

    assert len(msgs) == 3  # system + last 2
    assert [m["content"] for m in msgs[1:]] == ["2", "3"]
