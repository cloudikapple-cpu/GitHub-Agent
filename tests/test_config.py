from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from jarvis.config import (  # noqa: E402 - imported after the yaml guard
    NIM_BASE_URL,
    SOURCE_ENV,
    SOURCE_YAML,
    Config,
)

CONFIG = """
backend: my-gateway
providers:
  my-gateway:
    kind: openai
    model: llama-3.3-70b
    base_url: https://api.example.com/v1
    api_key: secret-token
    headers:
      X-Title: Jarvis
    temperature: 0.2
security:
  allow_app_management: true
  allowed_roots:
    - ~/projects
integrations:
  hass:
    base_url: http://homeassistant.local:8123/api
interface:
  hotkey: ctrl+shift+j
voice:
  enabled: true
  language: ru
"""

#: A file that names a provider and a model, exactly like a stale config.yaml.
NIM_CONFIG = """
backend: openai
providers:
  nim:
    kind: openai
    model: model-from-the-file
"""

#: Environment variables that must not leak between tests.
ENVIRONMENT = (
    "JARVIS_BACKEND",
    "JARVIS_MAX_ITERATIONS",
    "JARVIS_SANDBOX",
    "NVIDIA_MODEL",
    "NVIDIA_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_BASE_URL",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def test_custom_provider_is_loaded(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")

    config = Config.load(path)
    provider = config.provider()

    assert config.backend == "my-gateway"
    assert provider.kind == "openai"
    assert provider.base_url == "https://api.example.com/v1"
    assert provider.api_key == "secret-token"
    assert provider.headers["X-Title"] == "Jarvis"
    assert provider.temperature == 0.2


def test_builtin_providers_always_exist(tmp_path: Path):
    config = Config.load(tmp_path / "missing.yaml")
    for name in ("openai", "anthropic", "ollama"):
        assert config.provider(name).kind == name


def test_unknown_backend_raises(tmp_path: Path):
    config = Config.load(tmp_path / "missing.yaml")
    with pytest.raises(ValueError):
        config.provider("nope")


def test_policy_and_subsystems(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    config = Config.load(path)

    policy = config.policy()
    assert policy.allow_app_management is True
    assert policy.allowed_roots == ["~/projects"]
    assert config.integrations["hass"]["base_url"].startswith("http://")
    assert config.interface.hotkey == "ctrl+shift+j"
    assert config.voice.enabled is True


def test_shell_kill_switch_reaches_the_tool(tmp_path: Path):
    from jarvis.tools.shell import ShellTool

    config = Config.load(tmp_path / "missing.yaml")
    config.allow_shell = False
    tool = ShellTool(allow=config.allow_shell, policy=config.policy())

    assert "disabled" in tool.run(command="echo hi")


# ----------------------------------------------------------------------
# precedence: defaults < config.yaml < environment
# ----------------------------------------------------------------------
def test_the_config_file_is_used_when_the_environment_is_silent(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(NIM_CONFIG, encoding="utf-8")

    config = Config.load(path)

    assert config.backend == "openai"
    assert config.provider("nim").model == "model-from-the-file"
    assert config.source_of("backend") == SOURCE_YAML


def test_the_environment_beats_the_config_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(NIM_CONFIG, encoding="utf-8")
    monkeypatch.setenv("JARVIS_BACKEND", "nim")
    monkeypatch.setenv("NVIDIA_MODEL", "model-from-the-environment")

    config = Config.load(path)

    assert config.backend == "nim"
    assert config.provider().model == "model-from-the-environment"
    assert config.source_of("backend") == SOURCE_ENV
    assert config.overrides, "an override must be reported"


def test_the_source_of_a_setting_is_reported(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(NIM_CONFIG, encoding="utf-8")

    config = Config.load(path)

    assert str(path) in config.describe_source("backend")
    assert config.source_of("max_iterations") == "default"


def test_a_partial_provider_block_keeps_the_built_in_defaults(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(NIM_CONFIG, encoding="utf-8")

    config = Config.load(path)

    assert config.provider("nim").base_url == NIM_BASE_URL


def test_a_broken_number_in_the_environment_does_not_crash(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JARVIS_MAX_ITERATIONS", "twelve")

    config = Config.load(tmp_path / "missing.yaml")

    assert config.max_iterations == 12


def test_the_sandbox_switch_accepts_a_boolean(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JARVIS_SANDBOX", "false")

    config = Config.load(tmp_path / "missing.yaml")

    assert config.execution_sandbox.mode == "none"
