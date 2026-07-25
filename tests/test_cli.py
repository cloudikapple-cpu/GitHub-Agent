"""Command line surfaces that need neither a model nor a config file."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis import budget, cli


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    """An isolated usage ledger, so the tests never touch ~/.jarvis."""

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
    assert "0.75" in out  # $0.15 + $0.60 per million tokens


def test_the_usage_report_accepts_a_day(ledger, capsys):
    assert cli.main(["--usage", "2020-01-01"]) == 0
    assert "2020-01-01" in capsys.readouterr().out


def test_the_usage_report_needs_no_provider(ledger, capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["--usage"]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_the_parser_understands_the_usage_flag():
    parser = cli.build_parser()

    assert parser.parse_args(["--usage"]).usage == "today"
    assert parser.parse_args(["--usage", "2026-01-01"]).usage == "2026-01-01"
    assert parser.parse_args([]).usage is None
