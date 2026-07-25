"""Permission profiles must map cleanly onto the config flags."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.cli import PROFILES, apply_overrides, build_parser
from jarvis.config import Config


def _config(argv: list[str]) -> Config:
    args = build_parser().parse_args(argv)
    return apply_overrides(Config.load(None), args)


def test_every_profile_sets_the_same_keys():
    keys = [set(values) for values in PROFILES.values()]
    assert all(k == keys[0] for k in keys)


def test_safe_profile_locks_the_machine_down():
    config = _config(["--profile", "safe"])
    assert config.allow_shell is False
    assert config.allow_exec is False
    assert config.allow_desktop is False
    assert config.allow_app_management is False
    assert config.require_confirmation is True


def test_yolo_profile_opens_everything():
    config = _config(["--profile", "yolo"])
    assert config.allow_shell is True
    assert config.allow_desktop is True
    assert config.allow_app_management is True
    assert config.require_confirmation is False


def test_yolo_flag_matches_the_yolo_profile():
    flag = _config(["--yolo"])
    profile = _config(["--profile", "yolo"])
    assert flag.require_confirmation == profile.require_confirmation
    assert flag.allow_app_management == profile.allow_app_management


def test_explicit_flags_win_over_the_profile():
    config = _config(["--profile", "yolo", "--dry-run"])
    assert config.dry_run is True


def test_stream_flags_toggle_the_interface():
    assert _config(["--stream"]).interface.stream is True
    assert _config(["--no-stream"]).interface.stream is False
