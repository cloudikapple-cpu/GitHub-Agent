"""The reply cache: same question, same answer, no second bill."""

from jarvis.cache import MEMORY, ResponseCache, fingerprint
from jarvis.llm.base import LLMBackend, LLMResponse, ToolCall
from jarvis.llm.caching import CachingBackend

MESSAGES = [{"role": "user", "content": "hello"}]


class Recorder(LLMBackend):
    """A backend that counts how often it was actually asked."""

    name = "recorder"
    supports_streaming = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        return self.responses.pop(0)


def test_fingerprint_is_stable_and_specific():
    baseline = fingerprint("model", MESSAGES)
    assert baseline == fingerprint("model", [{"role": "user", "content": "hello"}])
    assert baseline != fingerprint("other-model", MESSAGES)
    assert baseline != fingerprint("model", [{"role": "user", "content": "hi"}])


def test_fingerprint_ignores_tool_order():
    tools = [{"name": "shell"}, {"name": "read_file"}]
    assert fingerprint("m", MESSAGES, tools) == fingerprint("m", MESSAGES, list(reversed(tools)))


def test_set_and_get_roundtrip():
    cache = ResponseCache(MEMORY)
    key = fingerprint("m", MESSAGES)

    assert cache.get(key) is None
    cache.set(key, "forty two", "m")
    assert cache.get(key) == "forty two"

    stats = cache.stats()
    assert stats.entries == 1
    assert stats.hits == 1
    assert stats.misses == 1
    assert "1 hits" in stats.format()
    cache.close()


def test_stale_entries_are_dropped():
    cache = ResponseCache(MEMORY, ttl=60)
    cache.set("key", "old answer")
    cache._connection.execute("UPDATE replies SET created = 0")
    cache._connection.commit()

    assert cache.get("key") is None
    assert cache.count() == 0
    cache.close()


def test_empty_answers_are_not_stored():
    cache = ResponseCache(MEMORY)
    assert cache.set("key", "   ") is False
    assert cache.count() == 0
    cache.close()


def test_a_disabled_cache_answers_nothing():
    cache = ResponseCache(MEMORY, enabled=False)
    cache.set("key", "value")
    assert cache.get("key") is None
    cache.close()


def test_prune_enforces_the_size_limit():
    cache = ResponseCache(MEMORY, max_entries=3)
    for index in range(6):
        cache.set(f"key-{index}", f"value-{index}")
    assert cache.count() == 3
    cache.close()


def test_clear_empties_the_cache():
    cache = ResponseCache(MEMORY)
    cache.set("key", "value")
    assert cache.clear() == 1
    assert cache.count() == 0
    cache.close()


# -- the backend wrapper -------------------------------------------------
def test_the_second_identical_request_is_free():
    inner = Recorder([LLMResponse(content="remembered")])
    backend = CachingBackend(inner, ResponseCache(MEMORY))

    first = backend.chat(MESSAGES)
    second = backend.chat(MESSAGES)

    assert inner.calls == 1
    assert second.content == first.content == "remembered"
    assert second.cached is True
    assert first.cached is False


def test_tool_calls_are_never_replayed():
    reply = LLMResponse(tool_calls=[ToolCall(id="1", name="shell", arguments={})])
    inner = Recorder([reply, reply])
    backend = CachingBackend(inner, ResponseCache(MEMORY))

    backend.chat(MESSAGES)
    backend.chat(MESSAGES)

    assert inner.calls == 2


def test_empty_replies_are_never_cached():
    silence = LLMResponse(content="the provider said nothing", empty=True)
    inner = Recorder([silence, silence])
    backend = CachingBackend(inner, ResponseCache(MEMORY))

    backend.chat(MESSAGES)
    backend.chat(MESSAGES)

    assert inner.calls == 2


def test_a_cached_answer_still_reaches_the_stream():
    inner = Recorder([LLMResponse(content="streamed once")])
    backend = CachingBackend(inner, ResponseCache(MEMORY))
    backend.chat(MESSAGES)

    chunks: list[str] = []
    response = backend.stream_response(MESSAGES, sink=chunks.append)

    assert inner.calls == 1
    assert "".join(chunks) == "streamed once"
    assert response.cached is True
