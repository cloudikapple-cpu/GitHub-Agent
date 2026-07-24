"""Tray icon lifecycle (without a real tray)."""

from __future__ import annotations

import jarvis.tray as tray_module
from jarvis.tray import TrayIcon


def build():
    events: list[str] = []
    icon = TrayIcon(
        on_open=lambda: events.append("open"),
        on_voice=lambda: events.append("voice"),
        on_quit=lambda: events.append("quit"),
        hotkey="ctrl+alt+space",
    )
    return icon, events


def test_start_is_a_no_op_without_pystray(monkeypatch):
    monkeypatch.setattr(tray_module, "TRAY_AVAILABLE", False)
    icon, _ = build()
    assert icon.start() is False
    assert icon.available() is False


def test_stop_does_not_quit_the_application():
    icon, events = build()
    icon.stop()
    assert events == []


def test_stop_is_idempotent():
    icon, events = build()
    icon.stop()
    icon.stop()
    assert events == []


def test_quit_from_the_menu_removes_the_icon_and_exits():
    icon, events = build()

    class FakeIcon:
        def __init__(self) -> None:
            self.stopped = False
            self.visible = True

        def stop(self) -> None:
            self.stopped = True

    fake = FakeIcon()
    icon._icon = fake
    icon.quit()
    assert fake.stopped is True
    assert icon._icon is None
    assert events == ["quit"]
