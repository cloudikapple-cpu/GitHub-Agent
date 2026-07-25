"""Streaming that survives tool calls, and a router that survives silence."""

from types import SimpleNamespace

from jarvis.agent import Agent
from jarvis.llm.base import LLMBackend, LLMResponse, ToolCall
from jarvis.llm.router import RoutingBackend


class ScriptedBackend(LLMBackend):
    """Replays prepared responses, word by word when streamed."""

    name = "scripted"
    supports_streaming = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.turns = 0

    def chat(self, messages, tools=None):
        self.turns += 1
        return self.responses.pop(0)

    def stream_response(self, messages, tools=None, sink=None):
        response = self.chat(messages, tools)
        if sink is not None and response.content and not response.wants_tools:
            for word in response.content.split(" "):
                sink(word + " ")
        return response


class StubTools:
    def __init__(self):
        self.calls = []

    def schemas(self):
        return [{"name": "echo", "description": "echo", "parameters": {}}]

    def get(self, name):
        return SimpleNamespace(requires_confirmation=False)

    def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return "tool finished"


def build_agent(responses):
    tools = StubTools()
    agent = Agent(ScriptedBackend(responses), tools, require_confirmation=False)
    return agent, tools


def test_streaming_continues_through_a_tool_call():
    agent, tools = build_agent(
        [
            LLMResponse(tool_calls=[ToolCall(id="1", name="echo", arguments={"text": "hi"})]),
            LLMResponse(content="all done"),
        ]
    )

    chunks = list(agent.stream("please do it"))

    assert tools.calls == [("echo", {"text": "hi"})]
    assert "".join(chunks).strip() == "all done"


def test_streaming_arrives_in_more_than_one_piece():
    agent, _ = build_agent([LLMResponse(content="one two three")])
    chunks = list(agent.stream("count"))
    assert len(chunks) > 1


def test_run_and_stream_produce_the_same_answer():
    agent, _ = build_agent([LLMResponse(content="the same answer")])
    assert agent.run("question") == "the same answer"

    agent, _ = build_agent([LLMResponse(content="the same answer")])
    assert "".join(agent.stream("question")).strip() == "the same answer"


def test_a_failing_run_reports_the_error_instead_of_hanging():
    class Exploding(LLMBackend):
        name = "exploding"

        def chat(self, messages, tools=None):
            raise RuntimeError("the endpoint is on fire")

    agent = Agent(Exploding(), StubTools(), require_confirmation=False)
    assert "on fire" in "".join(agent.stream("anything"))


def test_a_plain_backend_still_streams():
    class Plain(LLMBackend):
        name = "plain"

        def chat(self, messages, tools=None):
            return LLMResponse(content="one two")

    assert "".join(Plain().stream([{"role": "user", "content": "hi"}])) == "one two"


# -- the router ----------------------------------------------------------
class Silent(LLMBackend):
    name = "silent"

    def chat(self, messages, tools=None):
        return LLMResponse(content="the provider returned an empty message", empty=True)


class Speaks(LLMBackend):
    name = "speaks"

    def chat(self, messages, tools=None):
        return LLMResponse(content="a real answer")


def test_an_empty_reply_is_treated_as_a_failure():
    router = RoutingBackend({"a": Silent, "b": Speaks}, primary="a", fallbacks=["b"])
    response = router.chat([{"role": "user", "content": "hi"}])

    assert response.content == "a real answer"
    assert router.last_provider == "b"


def test_when_everyone_is_silent_the_explanation_is_returned():
    router = RoutingBackend({"a": Silent, "b": Silent}, primary="a", fallbacks=["b"])
    response = router.chat([{"role": "user", "content": "hi"}])

    assert response.empty is True
    assert "empty message" in response.content
