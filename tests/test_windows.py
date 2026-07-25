"""Windows 11 helpers: encoded PowerShell, toasts, task XML, hotkey probing."""

from __future__ import annotations

import base64
import platform

import pytest

from jarvis import notifications, windows


# ------------------------------------------------------------------ powershell
def test_encoded_command_round_trips_utf16():
    script = "Write-Output 'привет \"world\"'"
    decoded = base64.b64decode(windows.encode_command(script)).decode("utf-16-le")
    assert decoded == script


def test_the_argv_never_carries_the_raw_script():
    argv = windows.powershell_argv("Get-Process | Out-String")
    assert "-NoProfile" in argv
    assert "-NonInteractive" in argv
    assert argv[-2] == "-EncodedCommand"
    # The point of encoding: no quoting, no injection, nothing to escape.
    assert not any("Get-Process" in part for part in argv)


def test_the_interpreter_can_be_overridden(monkeypatch):
    monkeypatch.setenv("JARVIS_POWERSHELL", "C:/pwsh/pwsh.exe")
    assert windows.powershell_executable() == "C:/pwsh/pwsh.exe"


# ----------------------------------------------------------------------- toasts
def test_toast_xml_escapes_the_payload():
    xml = windows.toast_xml("Tom & Jerry", "<script>alert('x')</script>")
    assert "&amp;" in xml
    assert "<script>" not in xml
    assert "&lt;script&gt;" in xml


def test_toast_xml_renders_buttons():
    xml = windows.toast_xml("Report", "Ready", [("Open", "file:///c:/report.pdf")])
    assert "<actions>" in xml
    assert 'content="Open"' in xml
    assert 'activationType="protocol"' in xml


def test_a_toast_without_buttons_has_no_actions_block():
    assert "<actions>" not in windows.toast_xml("Title", "Body")


def test_the_toast_script_hides_every_string_in_base64():
    script = windows.toast_script("Secret title", "Secret body")
    assert "Secret title" not in script
    assert "FromBase64String" in script
    assert "CreateToastNotifier" in script


def test_toast_is_a_no_op_off_windows(monkeypatch):
    monkeypatch.setattr(windows, "IS_WINDOWS", False)
    assert windows.toast("Title", "Body") is False


def test_toast_reports_a_failed_powershell_call(monkeypatch):
    class Failed:
        returncode = 1
        stderr = "WinRT is unavailable"

    monkeypatch.setattr(windows, "IS_WINDOWS", True)
    monkeypatch.setattr(windows, "run_powershell", lambda script, timeout=30: Failed())
    assert windows.toast("Title", "Body") is False


def test_notify_prefers_the_toast_on_windows(monkeypatch):
    seen = {}

    def fake_toast(title, message, actions=None):
        seen["title"] = title
        seen["actions"] = actions
        return True

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(windows, "toast", fake_toast)
    result = notifications.notify("Jarvis", "Done", [("Open", "https://example.com")])
    assert result == "Notification shown."
    assert seen["title"] == "Jarvis"
    assert seen["actions"] == [("Open", "https://example.com")]


def test_notify_degrades_to_plain_text_when_nothing_works(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(windows, "toast", lambda *a, **k: False)
    monkeypatch.setattr(notifications, "_balloon", lambda title, message: False)
    assert notifications.notify("Jarvis", "Done") == "Jarvis: Done"


# -------------------------------------------------------------------- task xml
def test_task_xml_describes_a_delayed_logon_task():
    xml = windows.task_xml("C:/Jarvis/jarvis.cmd", delay="PT45S")
    assert "<LogonTrigger>" in xml
    assert "<Delay>PT45S</Delay>" in xml
    assert "<RestartOnFailure>" in xml
    assert "<Command>C:/Jarvis/jarvis.cmd</Command>" in xml


def test_task_xml_escapes_the_command():
    xml = windows.task_xml('C:/Program Files/A & B/jarvis.cmd')
    assert "A &amp; B" in xml


# --------------------------------------------------------------------- hotkeys
@pytest.mark.parametrize(
    ("combo", "expected"),
    [
        ("ctrl+alt+space", (0x0002 | 0x0001, 0x20)),
        ("ctrl+shift+j", (0x0002 | 0x0004, ord("J"))),
        ("win+f5", (0x0008, 0x74)),
    ],
)
def test_parse_combo_maps_to_virtual_keys(combo, expected):
    assert windows.parse_combo(combo) == expected


@pytest.mark.parametrize("combo", ["ctrl+alt", "ctrl+unknownkey", ""])
def test_parse_combo_refuses_what_it_cannot_express(combo):
    assert windows.parse_combo(combo) is None


def test_hotkey_availability_is_unknown_off_windows(monkeypatch):
    monkeypatch.setattr(windows, "IS_WINDOWS", False)
    assert windows.hotkey_available("ctrl+alt+space") is None


def test_the_manager_reports_a_taken_shortcut(monkeypatch):
    from jarvis.hotkey import HotkeyManager

    monkeypatch.setattr(windows, "hotkey_available", lambda combo: combo != "ctrl+alt+space")
    manager = HotkeyManager()
    manager.register("ctrl+alt+space", lambda: None)
    manager.register("ctrl+alt+v", lambda: None)
    assert manager.conflicts() == ["ctrl+alt+space"]


def test_unknown_availability_is_not_a_conflict(monkeypatch):
    from jarvis.hotkey import HotkeyManager

    monkeypatch.setattr(windows, "hotkey_available", lambda combo: None)
    manager = HotkeyManager()
    manager.register("ctrl+alt+space", lambda: None)
    assert manager.conflicts() == []
