"""The OpenAI-compatible backend must never turn an answer into silence.

These tests exercise the response parsing only, so they neither import the
``openai`` package nor touch the network.
"""

from __future__ import annotations

from jarvis.llm.openai_backend import (
    TRUNCATED_NOTE,
    extract_content,
)


class Message:
    """The parts of an SDK message object the parser looks at."""

    def __init__(self, content=None, **extra):
        self.content = content
        for key, value in extra.items():
            setattr(self, key, value)


class ExtraMessage:
    """A message whose extra fields live in ``model_extra``, as pydantic does it."""

    def __init__(self, content, model_extra):
        self.content = content
        self.model_extra = model_extra


def test_plain_content_is_returned():
    assert extract_content(Message(content="hello")) == "hello"


def test_reasoning_content_is_used_when_content_is_empty():
    message = Message(content="", reasoning_content="the real answer")

    assert extract_content(message) == "the real answer"


def test_reasoning_content_hidden_in_model_extra_is_found():
    message = ExtraMessage(None, {"reasoning_content": "the real answer"})

    assert extract_content(message) == "the real answer"


def test_content_parts_are_joined():
    message = Message(content=[{"text": "one "}, {"text": "two"}])

    assert extract_content(message) == "one two"


def test_content_wins_over_reasoning():
    message = Message(content="the answer", reasoning_content="thinking out loud")

    assert extract_content(message) == "the answer"


def test_a_truncated_answer_explains_itself():
    assert extract_content(Message(content=""), "length") == TRUNCATED_NOTE


def test_whitespace_only_content_counts_as_empty():
    assert extract_content(Message(content="   \n")) == ""


def test_nothing_at_all_returns_an_empty_string():
    assert extract_content(Message(content=None)) == ""
