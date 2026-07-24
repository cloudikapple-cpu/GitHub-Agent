from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from jarvis.config import Config  # noqa: E402 - imported after the yaml guard

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
