"""Retry helper: backoff, give-up behaviour and what counts as transient."""

from __future__ import annotations

import pytest

from jarvis.retry import RETRYABLE_STATUS, backoff_delay, call_with_retry, is_retryable


class Throttled(Exception):
    status_code = 429


class Fatal(Exception):
    status_code = 400


class Flaky:
    """Fails the first ``failures`` calls, then succeeds."""

    def __init__(self, failures: int, error: Exception):
        self.failures = failures
        self.error = error
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return "ok"


def _run(func, attempts=3, sleep=None):
    return call_with_retry(
        func,
        attempts=attempts,
        base_delay=0,
        max_delay=0,
        sleep=sleep or (lambda _: None),
    )


def test_retries_until_success():
    flaky = Flaky(2, Throttled())
    assert _run(flaky) == "ok"
    assert flaky.calls == 3


def test_gives_up_and_reraises_the_original_error():
    flaky = Flaky(9, Throttled())
    with pytest.raises(Throttled):
        _run(flaky)
    assert flaky.calls == 3


def test_permanent_failures_are_not_retried():
    flaky = Flaky(9, Fatal())
    with pytest.raises(Fatal):
        _run(flaky)
    assert flaky.calls == 1


def test_transient_exceptions_are_recognised_by_name():
    class ReadTimeout(Exception):
        pass

    assert is_retryable(ReadTimeout())
    assert not is_retryable(ValueError("bad input"))
    assert 503 in RETRYABLE_STATUS
    assert 404 not in RETRYABLE_STATUS


def test_backoff_doubles_and_is_capped():
    delays = [backoff_delay(i, base=1.0, cap=4.0, jitter=False) for i in range(1, 5)]
    assert delays == [1.0, 2.0, 4.0, 4.0]


def test_one_pause_per_retry():
    pauses: list[float] = []
    _run(Flaky(1, Throttled()), attempts=3, sleep=pauses.append)
    assert len(pauses) == 1
