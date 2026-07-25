"""Retry helpers: exponential backoff with jitter for flaky network calls.

Every outbound HTTP call in Jarvis - the search providers, page fetching and
the LLM backends - goes through :func:`call_with_retry`. A single timeout or a
``429`` from a provider used to abort the whole turn; now the call is repeated
a few times with growing pauses before the error reaches the agent.

Tuning through the environment:

* ``JARVIS_RETRY_ATTEMPTS``   - total attempts, default ``3`` (``1`` disables);
* ``JARVIS_RETRY_BASE_DELAY`` - first pause in seconds, default ``0.5``;
* ``JARVIS_RETRY_MAX_DELAY``  - pause ceiling in seconds, default ``8``.
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from typing import TypeVar

LOGGER = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.5
DEFAULT_MAX_DELAY = 8.0

#: HTTP statuses worth repeating: throttling and transient server faults.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

#: Exception class names raised by requests, httpx and the provider SDKs.
RETRYABLE_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectTimeout",
        "ConnectionError",
        "InternalServerError",
        "RateLimitError",
        "ReadTimeout",
        "RemoteProtocolError",
        "ServiceUnavailableError",
        "Timeout",
    }
)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def status_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status extraction from an arbitrary exception."""

    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def is_retryable(exc: BaseException) -> bool:
    """True when repeating the call has a realistic chance of succeeding."""

    status = status_of(exc)
    if status is not None:
        return status in RETRYABLE_STATUS
    names = {base.__name__ for base in type(exc).__mro__}
    return bool(names & RETRYABLE_NAMES)


def backoff_delay(attempt: int, base: float, cap: float, jitter: bool = True) -> float:
    """Pause before retry number ``attempt`` (1 is the first retry)."""

    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    if jitter:
        delay *= 0.5 + random.random() / 2
    return round(delay, 3)


def call_with_retry(
    func: Callable[[], T],
    *,
    attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    should_retry: Callable[[BaseException], bool] | None = None,
    description: str = "request",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``func`` and repeat it while the failure looks transient.

    The last exception is re-raised unchanged, so callers keep their existing
    error handling and error messages.
    """

    if attempts is None:
        attempts = _env_int("JARVIS_RETRY_ATTEMPTS", DEFAULT_ATTEMPTS)
    if base_delay is None:
        base_delay = _env_float("JARVIS_RETRY_BASE_DELAY", DEFAULT_BASE_DELAY)
    if max_delay is None:
        max_delay = _env_float("JARVIS_RETRY_MAX_DELAY", DEFAULT_MAX_DELAY)
    total = max(1, attempts)
    predicate = should_retry or is_retryable

    for attempt in range(1, total + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - re-raised when it is hopeless
            if attempt >= total or not predicate(exc):
                raise
            pause = backoff_delay(attempt, base_delay, max_delay)
            LOGGER.warning(
                "%s failed (%s); retrying in %.1fs (attempt %d of %d)",
                description,
                exc,
                pause,
                attempt + 1,
                total,
            )
            sleep(pause)

    raise RuntimeError("unreachable: the retry loop always returns or raises")
