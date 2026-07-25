"""Command line surfaces that do not need a model."""

from __future__ import annotations

import pytest

from jarvis import budget, cli


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    """An isolated usage ledger with one recorded call."""

    monkeypatch.setenv("JARVIS_USAGE_LOG", str(tmp_path / "usage.json"))
    monkeypatch.delenv("JARVIS_BUDGET_DAILY_USD", raising=False)
    budget.reset_default_tracker()
    yield budget.default_tracker()
    budget.reset_default_tracker()


def test_the_usage_report_shows_todays_spend(ledger, capsys):
    ledger.record("openai", "gpt-4o-mini", 1_000_000, 1_000_000)

    assert cli.main(["--usage"]) == 0

    out = capsys.readouterr().out
    assert "openai" in out
    assert "0.75" in out  # 0.15 + 0.60 per million tokens


def test_the_usage_report_accepts_a_day(ledger, capsys):
    assert cli.main(["--usage", "2020-01-01"]) == 0
    assert "2020-01-01" in capsys.readouterr().out


def test_the_usage_report_needs_no_provider(ledger, capsys, monkeypatch):
    # No API key, no config: the report must still work.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["--usage"]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_profiles_set_every_switch():
    from jarvis.config import Config

    config = cli.apply_profile(Config(), "safe")
    assert config.allow_shell is False
    assert config.allow_exec is False
    assert config.require_confirmation is True

    config = cli.apply_profile(Config(), "yolo")
    assert config.allow_app_management is True
    assert config.require_confirmation is False


def test_the_parser_knows_the_new_flags():
    parser = cli.build_parser()
    args = parser.parse_args(["--usage"])
    assert args.usage == "today"

    args = parser.parse_args(["--usage", "2026-01-01"])
    assert args.usage == "2026-01-01"

    args = parser.parse_args([])
    assert args.usage is None
