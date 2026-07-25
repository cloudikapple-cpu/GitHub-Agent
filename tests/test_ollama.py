"""Tests for the local Ollama backend.

Nothing here touches a real server: ``requests`` is replaced with fakes that
replay the shapes Ollama actually returns, including the newline-delimited
JSON of a streaming answer.
"""

from __future__ import annotations

import json

import pytest

from jarvis.config import ProviderConfig
from jarvis.llm import ollama_backend
from jarvis.llm.ollama_backend import OllamaBackend, looks_like_vision_model


@pytest.fixture(autouse=True)
def temporary_home(tmp_path, monkeypatch):
    """Keep the usage ledger out of the real home folder."""

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


class FakeResponse:
    def __init__(self, payload=None, lines=None):
        self._payload = payload or {}
        self._lines = lines or []

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_a_plain_answer_comes_back_as_content(monkeypatch):
    sent = {}

    def fake_post(url, json=None, timeout=None, **_kwargs):
        sent["url"] = url
        sent["payload"] = json
        return FakeResponse({"message": {"content": "hello"}, "eval_count": 2})

    monkeypatch.setattr(ollama_backend.requests, "post", fake_post)

    reply = OllamaBackend(model="llama3.1").chat([{"role": "user", "content": "hi"}])

    assert reply.content == "hello"
    assert reply.provider == "ollama"
    assert sent["url"].endswith("/api/chat")
    assert sent["payload"]["stream"] is False


def test_streaming_pushes_every_chunk_to_the_sink(monkeypatch):
    lines = [
        json.dumps({"message": {"content": "Hel"}, "done": False}),
        json.dumps({"message": {"content": "lo"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True, "eval_count": 5}),
    ]
    monkeypatch.setattr(
        ollama_backend.requests, "post", lambda *_a, **_k: FakeResponse(lines=lines)
    )

    chunks: list[str] = []
    reply = OllamaBackend().stream_response(
        [{"role": "user", "content": "hi"}], sink=chunks.append
    )

    assert chunks == ["Hel", "lo"]
    assert reply.content == "Hello"
    assert not reply.empty


def test_a_tool_call_is_parsed_and_streaming_is_skipped(monkeypatch):
    payloads = []

    def fake_post(url, json=None, timeout=None, **_kwargs):
        payloads.append(json)
        return FakeResponse(
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "read_file", "arguments": {"path": "a.txt"}}}
                    ],
                }
            }
        )

    monkeypatch.setattr(ollama_backend.requests, "post", fake_post)
    tools = [{"name": "read_file", "description": "read", "parameters": {}}]

    reply = OllamaBackend().stream_response([{"role": "user", "content": "read"}], tools)

    assert reply.wants_tools
    assert reply.tool_calls[0].name == "read_file"
    assert reply.tool_calls[0].arguments == {"path": "a.txt"}
    # Tool calls are requested without streaming, on purpose.
    assert payloads[0]["stream"] is False


def test_string_arguments_are_decoded(monkeypatch):
    monkeypatch.setattr(
        ollama_backend.requests,
        "post",
        lambda *_a, **_k: FakeResponse(
            {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "open", "arguments": '{"path": "b.txt"}'}}
                    ]
                }
            }
        ),
    )

    reply = OllamaBackend().chat([{"role": "user", "content": "open"}])

    assert reply.tool_calls[0].arguments == {"path": "b.txt"}


def test_images_are_attached_without_the_data_prefix(monkeypatch):
    sent = {}

    def fake_post(url, json=None, timeout=None, **_kwargs):
        sent["payload"] = json
        return FakeResponse({"message": {"content": "a cat"}})

    monkeypatch.setattr(ollama_backend.requests, "post", fake_post)

    OllamaBackend(model="llava").chat(
        [{"role": "user", "content": "what is this", "images": ["data:image/png;base64,QUJD"]}]
    )

    assert sent["payload"]["messages"][0]["images"] == ["QUJD"]


def test_an_unreachable_server_explains_how_to_start_it(monkeypatch):
    def fake_post(*_args, **_kwargs):
        raise ollama_backend.requests.RequestException("connection refused")

    monkeypatch.setattr(ollama_backend.requests, "post", fake_post)

    with pytest.raises(RuntimeError) as error:
        OllamaBackend(model="llama3.1").chat([{"role": "user", "content": "hi"}])

    assert "ollama serve" in str(error.value)
    assert "ollama pull llama3.1" in str(error.value)


def test_provider_settings_reach_the_request(monkeypatch):
    provider = ProviderConfig(
        name="ollama",
        kind="ollama",
        model="qwen2.5",
        base_url="http://127.0.0.1:11434",
        temperature=0.2,
        max_tokens=256,
        extra_body={"num_ctx": 4096, "keep_alive": "10m"},
    )
    backend = OllamaBackend.from_provider(provider)
    sent = {}

    def fake_post(url, json=None, timeout=None, **_kwargs):
        sent["payload"] = json
        return FakeResponse({"message": {"content": "ok"}})

    monkeypatch.setattr(ollama_backend.requests, "post", fake_post)
    backend.chat([{"role": "user", "content": "hi"}])

    assert backend.model == "qwen2.5"
    assert sent["payload"]["options"]["temperature"] == 0.2
    assert sent["payload"]["options"]["num_predict"] == 256
    assert sent["payload"]["options"]["num_ctx"] == 4096
    assert sent["payload"]["keep_alive"] == "10m"


def test_pulled_models_are_listed(monkeypatch):
    monkeypatch.setattr(
        ollama_backend.requests,
        "get",
        lambda *_a, **_k: FakeResponse({"models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5"}]}),
    )

    backend = OllamaBackend(model="llama3.1")

    assert backend.list_models() == ["llama3.1:8b", "qwen2.5"]
    assert backend.available() is True


def test_an_unreachable_server_lists_nothing(monkeypatch):
    def fake_get(*_args, **_kwargs):
        raise ollama_backend.requests.RequestException("refused")

    monkeypatch.setattr(ollama_backend.requests, "get", fake_get)

    assert OllamaBackend().list_models() == []
    assert OllamaBackend().available() is False


def test_vision_models_are_recognised_by_name():
    assert looks_like_vision_model("llama3.2-vision")
    assert looks_like_vision_model("llava:13b")
    assert not looks_like_vision_model("llama3.1")
