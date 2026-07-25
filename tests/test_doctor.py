"""Tests for the preflight diagnostics.

The checks must never touch the network or the real home folder here, so the
probe is disabled and HOME is redirected to a temporary directory.
"""

from __future__ import annotations

import pytest

from jarvis import doctor
from jarvis.config import Config, ProviderConfig


@pytest.fixture(autouse=True)
def temporary_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _config(**provider_kwargs) -> Config:
    config = Config()
    defaults = {"name": "openai", "kind": "openai", "model": "gpt-4o-mini"}
    defaults.update(provider_kwargs)
    config.backend = defaults["name"]
    config.providers = {defaults["name"]: ProviderConfig(**defaults)}
    return config


def _named(checks, name):
    for check in checks:
        if check.name == name:
            return check
    return None


def test_a_missing_api_key_blocks_the_run():
    checks = doctor.diagnose(_config(api_key=""), probe=False)

    assert _named(checks, "api key").status == doctor.FAIL
    assert doctor.has_failures(checks)


def test_a_present_api_key_passes():
    checks = doctor.diagnose(_config(api_key="sk-test-key"), probe=False)

    assert _named(checks, "api key").status == doctor.OK


def test_an_unknown_backend_is_reported_once():
    config = _config(api_key="sk-test-key")
    config.backend = "does-not-exist"

    checks = doctor.diagnose(config, probe=False)
    provider_checks = [check for check in checks if check.name == "provider"]

    assert len(provider_checks) == 1
    assert provider_checks[0].status == doctor.FAIL
    assert "does-not-exist" in provider_checks[0].detail


def test_a_model_less_provider_blocks_the_run():
    checks = doctor.diagnose(_config(model="", api_key="sk-test-key"), probe=False)

    assert _named(checks, "model").status == doctor.FAIL


def test_ollama_is_not_probed_when_probing_is_off():
    config = _config(name="ollama", kind="ollama", model="llama3.1")

    checks = doctor.diagnose(config, probe=False)

    assert _named(checks, "ollama") is None
    assert _named(checks, "api key") is None


def test_a_local_model_needs_no_api_key(monkeypatch):
    config = _config(name="ollama", kind="ollama", model="llama3.1")
    monkeypatch.setattr(doctor, "_port_open", lambda *_args, **_kwargs: True)

    checks = doctor.diagnose(config, probe=True)

    assert _named(checks, "ollama").status == doctor.OK
    assert not doctor.has_failures([c for c in checks if c.name != "sdk"])


def test_an_unreachable_ollama_blocks_the_run(monkeypatch):
    config = _config(name="ollama", kind="ollama", model="llama3.1")
    monkeypatch.setattr(doctor, "_port_open", lambda *_args, **_kwargs: False)

    checks = doctor.diagnose(config, probe=True)

    assert _named(checks, "ollama").status == doctor.FAIL
    assert "ollama pull llama3.1" in _named(checks, "ollama").fix


def test_missing_config_and_env_are_warnings_not_failures():
    checks = doctor.diagnose(_config(api_key="sk-test-key"), config_path="config.yaml", probe=False)

    assert _named(checks, "config").status == doctor.WARN
    assert _named(checks, "env file").status == doctor.WARN


def test_an_existing_config_file_is_found(temporary_home):
    (temporary_home / "config.yaml").write_text("backend: openai\n", encoding="utf-8")
    (temporary_home / ".env").write_text("OPENAI_API_KEY=x\n", encoding="utf-8")

    checks = doctor.diagnose(_config(api_key="sk-test-key"), config_path="config.yaml", probe=False)

    assert _named(checks, "config").status == doctor.OK
    assert _named(checks, "env file").status == doctor.OK


def test_the_state_folder_is_created():
    checks = doctor.diagnose(_config(api_key="sk-test-key"), probe=False)

    assert _named(checks, "state folder").status == doctor.OK


def test_disabled_confirmations_are_flagged():
    config = _config(api_key="sk-test-key")
    config.require_confirmation = False
    config.allow_shell = True

    assert doctor.check_permissions(config).status == doctor.WARN


def test_read_only_permissions_are_described():
    config = _config(api_key="sk-test-key")
    config.allow_shell = False
    config.allow_exec = False
    config.allow_desktop = False
    config.allow_app_management = False
    config.allow_network = False

    assert "read-only" in doctor.check_permissions(config).detail


def test_the_report_shows_fixes_and_a_verdict():
    checks = doctor.diagnose(_config(api_key=""), probe=False)

    report = doctor.format_report(checks)

    assert "fix:" in report
    assert "blocking problem" in report


def test_a_clean_report_invites_the_user_to_start():
    checks = [doctor.Check("python", doctor.OK, "3.12")]

    assert "Run 'jarvis' to start" in doctor.format_report(checks)
