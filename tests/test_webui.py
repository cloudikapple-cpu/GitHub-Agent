"""The browser interface, exercised over real HTTP on a random port."""

import json
import urllib.error
import urllib.request

import pytest

from jarvis.webui import WebServer, build_url


class StubAgent:
    def __init__(self):
        self.seen = []
        self.on_event = None

    def run(self, message):
        self.seen.append(message)
        return f"echo: {message}"

    def stream(self, message):
        self.seen.append(message)
        yield "echo: "
        yield message


@pytest.fixture
def server():
    web = WebServer(StubAgent(), port=0, stream=False)
    web.start()
    yield web
    web.stop()


def call(server, path, payload=None):
    url = f"http://127.0.0.1:{server.port}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"X-Jarvis-Token": server.token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def test_the_page_is_served_without_a_token(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=15) as response:
        body = response.read().decode("utf-8")
    assert "<title>Jarvis</title>" in body


def test_the_api_requires_a_token(server):
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(f"http://127.0.0.1:{server.port}/api/history", timeout=15)
    assert failure.value.code == 403


def test_health_reports_the_server_is_idle(server):
    payload = call(server, "/api/health")
    assert payload["ok"] is True
    assert payload["busy"] is False


def test_a_message_is_answered_and_remembered(server):
    payload = call(server, "/api/chat", {"message": "hello", "wait": True})
    assert payload["reply"] == "echo: hello"

    history = call(server, "/api/history")["history"]
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[1]["text"] == "echo: hello"


def test_an_empty_message_is_refused(server):
    with pytest.raises(urllib.error.HTTPError) as failure:
        call(server, "/api/chat", {"message": "   ", "wait": True})
    assert failure.value.code == 400


def test_streaming_publishes_chunks_then_the_final_answer():
    web = WebServer(StubAgent(), port=0, stream=True)
    listener = web.subscribe()

    assert web.ask("hi") == "echo: hi"

    kinds = []
    while not listener.empty():
        kinds.append(listener.get()["kind"])
    assert kinds[0] == "user"
    assert "chunk" in kinds
    assert kinds[-1] == "assistant"


def test_a_failing_agent_becomes_an_error_event():
    class Broken(StubAgent):
        def run(self, message):
            raise RuntimeError("tool exploded")

        def stream(self, message):
            raise RuntimeError("tool exploded")

    web = WebServer(Broken(), port=0, stream=False)
    listener = web.subscribe()
    web.ask("hi")

    kinds = []
    while not listener.empty():
        kinds.append(listener.get()["kind"])
    assert kinds[-1] == "error"


def test_a_wildcard_binding_is_printed_as_loopback():
    assert build_url("0.0.0.0", 8765, "abc") == "http://127.0.0.1:8765/?token=abc"
    assert build_url("127.0.0.1", 80, "t") == "http://127.0.0.1:80/?token=t"
