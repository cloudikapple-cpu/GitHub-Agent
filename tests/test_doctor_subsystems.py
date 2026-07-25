"""Tests for the 0.6/0.7 checks: cache, documents, web, keychain, voice, models."""

from __future__ import annotations

import pytest

from jarvis import doctor
from jarvis.config import Config


@pytest.fixture(autouse=True)
def temporary_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_a_writable_cache_passes():
    check = doctor.check_cache(Config())

    assert check.status == doctor.OK
    assert "cache.db" in check.detail


def test_a_disabled_cache_is_reported_as_off():
    config = Config()
    config.cache.enabled = False

    assert doctor.check_cache(config).detail == "off"


def test_documents_are_only_checked_when_retrieval_is_on():
    assert doctor.check_documents(Config()) is None


def test_retrieval_without_an_index_asks_for_one():
    config = Config()
    config.rag.enabled = True

    check = doctor.check_documents(config)

    assert check.status == doctor.WARN
    assert "--index" in check.fix


def test_the_web_check_prints_a_real_url():
    config = Config()
    config.web.enabled = True

    check = doctor.check_web(config, probe=False)

    assert check.status == doctor.OK
    assert check.detail.startswith("http://127.0.0.1:8765")
    assert "{" not in check.detail


def test_a_public_binding_is_flagged():
    config = Config()
    config.web.enabled = True
    config.web.host = "0.0.0.0"

    check = doctor.check_web(config, probe=False)

    assert check.status == doctor.WARN


def test_a_busy_port_is_flagged(monkeypatch):
    config = Config()
    config.web.enabled = True
    monkeypatch.setattr(doctor, "_port_open", lambda *_a, **_k: True)

    assert doctor.check_web(config, probe=True).status == doctor.WARN


def test_the_keychain_check_never_fails():
    assert doctor.check_keychain(Config()).status in {doctor.OK, doctor.WARN}


def test_a_missing_ollama_model_is_a_blocking_problem(monkeypatch):
    monkeypatch.setattr(doctor, "_ollama_models", lambda _host: ["qwen2.5:7b"])

    checks = doctor._check_ollama_model("http://localhost:11434", "llama3.1")

    assert checks[0].status == doctor.FAIL
    assert "ollama pull llama3.1" in checks[0].fix


def test_a_pulled_model_passes(monkeypatch):
    monkeypatch.setattr(doctor, "_ollama_models", lambda _host: ["llama3.1:8b"])

    checks = doctor._check_ollama_model("http://localhost:11434", "llama3.1")

    assert checks[0].status == doctor.OK


def test_a_silent_server_is_only_a_warning(monkeypatch):
    monkeypatch.setattr(doctor, "_ollama_models", lambda _host: [])

    checks = doctor._check_ollama_model("http://localhost:11434", "llama3.1")

    assert checks[0].status == doctor.WARN


def test_groq_voice_without_a_key_is_a_blocking_problem():
    config = Config()
    config.voice.enabled = True
    config.voice.stt = "groq"

    assert doctor.check_voice(config).status == doctor.FAIL


def test_groq_voice_with_a_key_needs_no_local_whisper(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setattr(doctor, "_missing", lambda _modules: [])
    config = Config()
    config.voice.enabled = True
    config.voice.stt = "groq"

    check = doctor.check_voice(config)

    assert check.status == doctor.OK
    assert "Groq" in check.detail


def test_the_full_report_stays_readable():
    config = Config()
    config.providers["openai"].api_key = "sk-test"

    report = doctor.format_report(doctor.diagnose(config, probe=False))

    assert "reply cache" in report
    assert "keychain" in report
