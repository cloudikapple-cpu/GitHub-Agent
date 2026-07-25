"""Token and spend accounting."""

from __future__ import annotations

import json

import pytest

from jarvis.budget import (
    BudgetExceeded,
    BudgetTracker,
    estimate_tokens,
    price_for,
    usage_from_openai,
)


def make_tracker(tmp_path, limit=None):
    return BudgetTracker(daily_limit_usd=limit, path=tmp_path / "usage.json")


def test_cost_comes_from_the_price_table(tmp_path):
    usage = make_tracker(tmp_path).record("openai", "gpt-4o-mini", 1_000_000, 1_000_000)
    assert usage.cost_usd == pytest.approx(0.75)
    assert usage.total_tokens == 2_000_000


def test_local_providers_are_free(tmp_path):
    tracker = make_tracker(tmp_path)
    usage = tracker.record("ollama", "llama3.1", 5_000, 5_000)
    assert usage.cost_usd == 0.0
    assert tracker.spent_today() == 0.0
    assert tracker.tokens_today() == 10_000


def test_the_daily_limit_blocks_further_calls(tmp_path):
    tracker = make_tracker(tmp_path, limit=0.5)
    tracker.check()  # nothing spent yet
    tracker.record("openai", "gpt-4o", 1_000_000, 0)  # 2.50 USD
    with pytest.raises(BudgetExceeded):
        tracker.check()


def test_no_limit_means_no_ceiling(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.record("openai", "gpt-4o", 10_000_000, 10_000_000)
    tracker.check()


def test_the_ledger_survives_a_restart(tmp_path):
    path = tmp_path / "usage.json"
    BudgetTracker(path=path).record("openai", "gpt-4o-mini", 1_000, 1_000)
    reloaded = BudgetTracker(path=path)
    assert reloaded.tokens_today() == 2_000
    assert json.loads(path.read_text(encoding="utf-8"))


def test_price_lookup_prefers_the_most_specific_match():
    assert price_for("gpt-4o-mini") == (0.15, 0.60)
    assert price_for("gpt-4o") == (2.50, 10.00)
    assert price_for("a-model-nobody-priced") == (0.0, 0.0)
    assert price_for("gpt-4o", provider="ollama") == (0.0, 0.0)


def test_report_lists_providers_and_a_total(tmp_path):
    tracker = make_tracker(tmp_path, limit=10)
    tracker.record("openai", "gpt-4o-mini", 100, 100)
    report = tracker.report()
    assert "openai" in report
    assert "total" in report
    assert "daily limit" in report


def test_token_estimation_and_extraction():
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens("") == 1

    class Usage:
        prompt_tokens = 12
        completion_tokens = 34

    class Completion:
        usage = Usage()

    assert usage_from_openai(Completion()) == (12, 34)
    assert usage_from_openai(object()) == (0, 0)
