"""Keychain references: `keyring:NAME` instead of a key in a file."""

from jarvis import secrets as keychain
from jarvis.config import SOURCE_KEYRING, Config


class FakeKeyring:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_password(self, service, name):
        return self.values.get((service, name))

    def set_password(self, service, name, value):
        self.values[(service, name)] = value

    def delete_password(self, service, name):
        self.values.pop((service, name))


def test_references_are_recognised():
    assert keychain.is_reference("keyring:NVIDIA_API_KEY")
    assert not keychain.is_reference("nvapi-plain-key")
    assert not keychain.is_reference(None)


def test_a_reference_may_name_its_service():
    assert keychain.parse_reference("keyring:KEY") == (keychain.SERVICE, "KEY")
    assert keychain.parse_reference("keyring:work/KEY") == ("work", "KEY")


def test_plain_values_pass_through_untouched():
    assert keychain.resolve("plain-value") == "plain-value"
    assert keychain.resolve("") == ""


def test_the_keychain_wins_when_it_has_the_secret(monkeypatch):
    monkeypatch.setattr(
        keychain, "_keyring", lambda: FakeKeyring({("jarvis", "KEY"): "from-keychain"})
    )
    monkeypatch.setenv("KEY", "from-environment")
    assert keychain.resolve("keyring:KEY") == "from-keychain"


def test_the_environment_is_the_fallback(monkeypatch):
    monkeypatch.setattr(keychain, "_keyring", lambda: None)
    monkeypatch.setenv("KEY", "from-environment")
    assert keychain.resolve("keyring:KEY") == "from-environment"


def test_a_missing_secret_becomes_an_empty_string(monkeypatch):
    monkeypatch.setattr(keychain, "_keyring", lambda: None)
    monkeypatch.delenv("ABSENT", raising=False)
    assert keychain.resolve("keyring:ABSENT") == ""


def test_writing_and_deleting_a_secret(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(keychain, "_keyring", lambda: fake)

    assert keychain.set_secret("KEY", "value") is True
    assert keychain.get_secret("KEY") == "value"
    assert keychain.delete_secret("KEY") is True
    assert keychain.get_secret("KEY") == ""


def test_config_resolves_provider_references(monkeypatch, tmp_path):
    monkeypatch.setattr(
        keychain, "_keyring", lambda: FakeKeyring({("jarvis", "MY_KEY"): "s3cret"})
    )
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "backend: nim\nproviders:\n  nim:\n    api_key: keyring:MY_KEY\n", encoding="utf-8"
    )

    config = Config.load(config_file)

    assert config.providers["nim"].api_key == "s3cret"
    assert config.source_of("providers.nim.api_key") == SOURCE_KEYRING
