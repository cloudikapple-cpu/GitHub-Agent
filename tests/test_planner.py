"""The planning step: cheap thinking before expensive acting."""

from types import SimpleNamespace

from jarvis.planner import Planner, format_plan, parse_plan


class StubBackend:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        return SimpleNamespace(content=self.text)


class BrokenBackend:
    def chat(self, messages, tools=None):
        raise RuntimeError("the planning endpoint is down")


def test_numbered_lists_are_understood():
    steps = parse_plan("1. Open the file\n2. Fix the bug\n3. Run the tests")
    assert steps == ["Open the file", "Fix the bug", "Run the tests"]


def test_bullets_and_json_are_understood():
    assert parse_plan("- one\n- two") == ["one", "two"]
    assert parse_plan('["one", "two"]') == ["one", "two"]


def test_the_step_limit_is_respected():
    text = "\n".join(f"{index}. step {index}" for index in range(1, 12))
    assert len(parse_plan(text, max_steps=4)) == 4


def test_nothing_in_nothing_out():
    assert parse_plan("") == []
    assert format_plan([]) == ""


def test_a_plan_is_rendered_for_the_agent():
    rendered = format_plan(["one", "two"])
    assert "1. one" in rendered
    assert "2. two" in rendered


def test_the_planner_returns_steps():
    assert Planner(StubBackend("1. one\n2. two")).plan("anything") == ["one", "two"]


def test_short_requests_are_not_worth_planning():
    backend = StubBackend("1. one")
    planner = Planner(backend)

    assert planner.context("hi") == ""
    assert backend.calls == 0


def test_long_requests_are_planned():
    backend = StubBackend("1. one\n2. two")
    planner = Planner(backend, min_chars=10)

    assert "1. one" in planner.context("a request long enough to deserve a plan")
    assert backend.calls == 1


def test_a_broken_planner_never_blocks_the_run():
    assert Planner(BrokenBackend()).plan("do something involved") == []


def test_answer_directly_means_no_plan():
    assert Planner(StubBackend("Answer directly")).plan("what is 2 + 2?") == []
