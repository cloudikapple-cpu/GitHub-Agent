"""The desktop tools must honour the security policy.

These tests never touch a real screen or keyboard: every case is refused by the
policy before pyautogui would be imported.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.security import SecurityError, SecurityPolicy
from jarvis.tools.desktop import HotkeyTool, OpenPathTool, ScreenshotTool, TypeTextTool


def test_desktop_tools_refuse_when_desktop_is_disabled(tmp_path):
    policy = SecurityPolicy(allow_desktop=False)

    with pytest.raises(SecurityError):
        TypeTextTool(policy).run(text="hello", delay=0)
    with pytest.raises(SecurityError):
        HotkeyTool(policy).run(keys=["ctrl", "c"])
    with pytest.raises(SecurityError):
        ScreenshotTool(policy).run(path=str(tmp_path / "shot.png"))
    with pytest.raises(SecurityError):
        OpenPathTool(policy).run(target=str(tmp_path))


def test_open_path_refuses_executables_when_shell_is_disabled(tmp_path):
    payload = tmp_path / "payload.exe"
    payload.write_text("stub", encoding="utf-8")

    policy = SecurityPolicy(allow_shell=False)
    with pytest.raises(SecurityError):
        OpenPathTool(policy).run(target=str(payload))


def test_open_path_respects_allowed_roots(tmp_path):
    policy = SecurityPolicy(allowed_roots=[str(tmp_path)])
    outside = tmp_path.parent / "outside-the-workspace.txt"

    with pytest.raises(SecurityError):
        OpenPathTool(policy).run(target=str(outside))


def test_open_path_refuses_urls_when_network_is_disabled():
    policy = SecurityPolicy(allow_network=False)
    with pytest.raises(SecurityError):
        OpenPathTool(policy).run(target="https://example.com")


def test_screenshot_path_is_checked_before_capture(tmp_path):
    policy = SecurityPolicy(allowed_roots=[str(tmp_path)])
    with pytest.raises(SecurityError):
        ScreenshotTool(policy).run(path=str(tmp_path.parent / "shot.png"))
