"""Tests for hosted transcription through Groq.

The microphone and the network are both out of scope here: only the engine
choice, the model name and the request/response handling are checked.
"""

from __future__ import annotations

import pytest
import requests

from jarvis.config import VoiceConfig
from jarvis.voice import VoiceError, VoiceIO, groq_api_key, transcription_available


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "input.wav"
    path.write_bytes(b"RIFF0000WAVE")
    return path


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self._payload = payload or {}
        self.status_code = status

    def json(self):
        return self._payload


def test_auto_picks_groq_when_a_key_is_present(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    assert VoiceIO(VoiceConfig(stt="auto")).engine() == "groq"


def test_auto_falls_back_to_local_whisper_without_a_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert VoiceIO(VoiceConfig(stt="auto")).engine() == "whisper"


def test_a_local_size_is_not_sent_to_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    voice = VoiceIO(VoiceConfig(stt="groq", whisper_model="base"))

    assert voice.groq_model() == "whisper-large-v3-turbo"


def test_an_explicit_groq_model_is_kept(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    voice = VoiceIO(VoiceConfig(stt="groq", whisper_model="whisper-large-v3"))

    assert voice.groq_model() == "whisper-large-v3"


def test_the_recording_is_posted_and_the_text_returned(monkeypatch, recording):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    sent = {}

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        sent["url"] = url
        sent["headers"] = headers
        sent["data"] = data
        return FakeResponse({"text": " привет "})

    monkeypatch.setattr(requests, "post", fake_post)
    voice = VoiceIO(VoiceConfig(stt="groq", language="ru"))

    assert voice.transcribe(recording) == "привет"
    assert sent["url"].endswith("/audio/transcriptions")
    assert sent["headers"]["Authorization"] == "Bearer gsk-test"
    assert sent["data"]["language"] == "ru"


def test_a_rejected_key_falls_back_and_says_what_is_missing(monkeypatch, recording):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-wrong")
    monkeypatch.setattr(requests, "post", lambda *_a, **_k: FakeResponse(status=401))
    voice = VoiceIO(VoiceConfig(stt="groq"))

    # Groq refuses, the local engine is not installed in CI: the user gets the
    # actionable message instead of a traceback.
    with pytest.raises(VoiceError):
        voice.transcribe(recording)


def test_a_missing_key_is_reported(monkeypatch, recording):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    voice = VoiceIO(VoiceConfig(stt="groq"))

    with pytest.raises(VoiceError):
        voice.transcribe(recording)


def test_the_key_can_come_from_the_config(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    config = VoiceConfig(stt="groq")
    config.stt_api_key = "gsk-from-config"  # type: ignore[attr-defined]

    assert groq_api_key(config) == "gsk-from-config"


def test_transcription_is_available_with_a_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    assert transcription_available(VoiceConfig()) is True
