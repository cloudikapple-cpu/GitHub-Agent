"""Login item management."""

from __future__ import annotations

import sys

import pytest

from jarvis import autostart


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


def test_install_then_remove_round_trip(home):
    assert "disabled" in autostart.status()
    assert "installed" in autostart.install()

    path = autostart.target_path()
    assert path.exists()
    assert "jarvis" in path.read_text(encoding="utf-8")
    assert "--daemon" in path.read_text(encoding="utf-8")
    assert "enabled" in autostart.status()

    assert "removed" in autostart.uninstall()
    assert not path.exists()
    assert autostart.uninstall() == "Autostart was not installed."


def test_the_entry_lands_in_the_platform_location(home):
    path = autostart.target_path()
    if sys.platform.startswith("win"):
        assert path.name == "jarvis.cmd"
    elif sys.platform == "darwin":
        assert path.suffix == ".plist"
    else:
        assert path.parent.name == "autostart" and path.suffix == ".desktop"
