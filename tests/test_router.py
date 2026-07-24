"""Routing between a local model and a cloud fallback."""

from __future__ import annotations

import pytest

from jarvis.llm.base import LLMBackend, LLMResponse
from jarvis.llm.router import RoutingBackend


class DummyBackend(LLMBackend):
    def __init__(self, name: str, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} is down")
        return LLMResponse(content=f"answer from {self.name}")


def build(primary_fails: bool = False):
    local = DummyBackend("ollama", fail=primary_fails)
    cloud = DummyBackend("nim")
    router = RoutingBackend(
        factories={"ollama": lambda: local, "nim": lambda: cloud},
        primary="ollama",
        fallbacks=["nim"],
        heavy="nim",
        escalate_over_chars=100,
    )
    return router, local, cloud


def test_primary_answers_first():
    router, local, cloud = build()
    response = router.chat([{"role": "user", "content": "hi"}])
    assert response.content == "answer from ollama"
    assert response.provider == "ollama"
    assert cloud.calls == 0


def test_falls_back_when_the_local_model_is_down():
    router, local, cloud = build(primary_fails=True)
    response = router.chat([{"role": "user", "content": "hi"}])
    assert response.content == "answer from nim"
    assert local.calls == 1 and cloud.calls == 1


def test_long_requests_escalate_to_the_heavy_provider():
    router, local, cloud = build()
    router.chat([{"role": "user", "content": "x" * 500}])
    assert cloud.calls == 1 and local.calls == 0


def test_all_providers_failing_raises():
    down_a = DummyBackend("a", fail=True)
    down_b = DummyBackend("b", fail=True)
    router = RoutingBackend(
        factories={"a": lambda: down_a, "b": lambda: down_b}, primary="a", fallbacks=["b"]
    )
    with pytest.raises(RuntimeError):
        router.chat([{"role": "user", "content": "hi"}])


def test_streaming_uses_the_default_chunking():
    router, _, _ = build()
    assert "".join(router.stream([{"role": "user", "content": "hi"}])) == "answer from ollama"
