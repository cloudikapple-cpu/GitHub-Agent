"""Login item management."""

from __future__ import annotations

import subprocess

import pytest

from jarvis import autostart, windows


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def posix(monkeypatch):
    """Pretend we are not on Windows, whatever the CI runner is."""

    monkeypatch.setattr(windows, "IS_WINDOWS", False)


@pytest.fixture()
def fake_schtasks(monkeypatch):
    """Pretend we are on Windows and record every schtasks call."""

    state = {"returncode": 0, "stderr": "", "calls": []}

    def schtasks(*args, timeout=30):
        state["calls"].append(list(args))
        return subprocess.CompletedProcess(list(args), state["returncode"], "", state["stderr"])

    monkeypatch.setattr(windows, "IS_WINDOWS", True)
    monkeypatch.setattr(windows, "schtasks", schtasks)
    monkeypatch.setattr(windows, "pythonw_executable", lambda: "C:/Python/pythonw.exe")
    return state


# --------------------------------------------------------------------- posix
def test_install_then_remove_round_trip(home, posix):
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


# ------------------------------------------------------------------- windows
def test_windows_installs_a_scheduled_task(home, fake_schtasks):
    message = autostart.install()

    assert "scheduled task" in message
    launcher = autostart.target_path()
    assert launcher.name == "jarvis.cmd"
    body = launcher.read_text(encoding="utf-8")
    assert "--daemon" in body
    # pythonw keeps the console window from flashing at every logon.
    assert "pythonw.exe" in body

    create = fake_schtasks["calls"][0]
    assert create[0] == "/Create"
    assert "/XML" in create
    assert windows.TASK_NAME in create


def test_the_startup_folder_is_the_fallback(home, fake_schtasks):
    fake_schtasks["returncode"] = 1
    fake_schtasks["stderr"] = "ERROR: Access is denied."

    message = autostart.install()

    assert "Startup" in message
    assert "Access is denied" in message
    assert autostart._startup_path().exists()


def test_a_successful_task_removes_the_old_shortcut(home, fake_schtasks):
    startup = autostart._startup_path()
    startup.parent.mkdir(parents=True, exist_ok=True)
    startup.write_text("stale", encoding="utf-8")

    autostart.install()

    # Two entries would launch two daemons at every logon.
    assert not startup.exists()


def test_windows_status_and_uninstall(home, fake_schtasks):
    autostart.install()
    assert "scheduled task" in autostart.status()

    message = autostart.uninstall()
    assert "removed" in message
    assert [call[0] for call in fake_schtasks["calls"]].count("/Delete") == 1
    assert not autostart.target_path().exists()


def test_windows_status_when_nothing_is_installed(home, fake_schtasks):
    fake_schtasks["returncode"] = 1
    assert "disabled" in autostart.status()
