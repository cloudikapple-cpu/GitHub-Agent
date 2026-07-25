"""Token and spend accounting.

The router happily sends heavy requests to a paid provider, so Jarvis keeps a
per-day ledger: how many tokens each provider consumed and what that cost.
When a daily limit is configured the tracker warns at 80% and refuses further
paid calls once the limit is reached.

Environment:

* ``JARVIS_BUDGET_DAILY_USD`` - daily ceiling in dollars (unset = unlimited);
* ``JARVIS_USAGE_LOG``        - ledger path, default ``~/.jarvis/usage.json``;
* ``JARVIS_PRICES``           - JSON overriding the built-in price table,
  for example ``'\u007b"gpt-4o-mini": [0.15, 0.6]\u007d'`` (USD per 1M tokens).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

DEFAULT_USAGE_PATH = Path.home() / ".jarvis" / "usage.json"
WARN_RATIO = 0.8
KEEP_DAYS = 30

#: (prompt, completion) price in USD per one million tokens, matched by substring.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-opus": (15.00, 75.00),
    "deepseek": (0.27, 1.10),
}

#: Providers that run on the user's own hardware and therefore cost nothing.
FREE_PROVIDERS = frozenset({"ollama", "local", "lmstudio", "llamacpp"})

_STATE: dict[str, Any] = {}
_STATE_LOCK = threading.Lock()


class BudgetExceeded(RuntimeError):
    """Raised when a paid call would push the day past the configured limit."""


@dataclass
class Usage:
    """What a single model call consumed."""

    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def estimate_tokens(text: str) -> int:
    """Rough count for providers that report no usage (about 4 chars per token)."""

    return max(1, len(text or "") // 4)


def _prices() -> dict[str, tuple[float, float]]:
    raw = os.environ.get("JARVIS_PRICES", "").strip()
    if not raw:
        return PRICES
    try:
        extra = json.loads(raw)
    except json.JSONDecodeError:
        LOGGER.warning("JARVIS_PRICES is not valid JSON; using the built-in table")
        return PRICES
    merged = dict(PRICES)
    for key, value in (extra or {}).items():
        try:
            merged[str(key)] = (float(value[0]), float(value[1]))
        except (TypeError, ValueError, IndexError, KeyError):
            LOGGER.warning("Ignoring the malformed price entry for %s", key)
    return merged


def price_for(model: str, provider: str = "") -> tuple[float, float]:
    """Price per 1M tokens for ``model``; local providers are always free."""

    if (provider or "").lower() in FREE_PROVIDERS:
        return (0.0, 0.0)
    name = (model or "").lower()
    best: tuple[float, float] = (0.0, 0.0)
    best_length = 0
    for prefix, price in _prices().items():
        key = prefix.lower()
        if key in name and len(key) > best_length:
            best, best_length = price, len(key)
    return best


def usage_from_openai(completion: Any) -> tuple[int, int]:
    """Extract (prompt, completion) tokens from an OpenAI-style response."""

    usage = getattr(completion, "usage", None)
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    output = getattr(usage, "completion_tokens", 0) or 0
    return int(prompt), int(output)


def usage_from_anthropic(response: Any) -> tuple[int, int]:
    """Extract (prompt, completion) tokens from an Anthropic response."""

    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "input_tokens", 0) or 0
    output = getattr(usage, "output_tokens", 0) or 0
    return int(prompt), int(output)


class BudgetTracker:
    """Thread-safe daily ledger persisted as JSON."""

    def __init__(
        self,
        daily_limit_usd: float | None = None,
        path: str | Path | None = None,
        warn_ratio: float = WARN_RATIO,
    ):
        self.daily_limit_usd = daily_limit_usd
        self.warn_ratio = warn_ratio
        self.path = Path(path).expanduser() if path else DEFAULT_USAGE_PATH
        self._lock = threading.RLock()
        self._warned = False
        self._data = self._load()

    # -- persistence ---------------------------------------------------
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:  # pragma: no cover - accounting must never break a run
            LOGGER.debug("Could not write the usage ledger to %s", self.path)

    def _today(self) -> dict[str, Any]:
        return self._data.setdefault(date.today().isoformat(), {})

    def _prune(self) -> None:
        if len(self._data) <= KEEP_DAYS:
            return
        for key in sorted(self._data)[: len(self._data) - KEEP_DAYS]:
            self._data.pop(key, None)

    # -- accounting ----------------------------------------------------
    def record(
        self, provider: str, model: str, prompt_tokens: int, completion_tokens: int
    ) -> Usage:
        """Add one call to today's ledger and return what it cost."""

        prompt_price, completion_price = price_for(model, provider)
        cost = (
            int(prompt_tokens) * prompt_price + int(completion_tokens) * completion_price
        ) / 1_000_000
        usage = Usage(
            provider=provider or "unknown",
            model=model or "unknown",
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            cost_usd=round(cost, 6),
        )
        with self._lock:
            bucket = self._today().setdefault(
                usage.provider,
                {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0},
            )
            bucket["calls"] += 1
            bucket["prompt_tokens"] += usage.prompt_tokens
            bucket["completion_tokens"] += usage.completion_tokens
            bucket["cost_usd"] = round(float(bucket["cost_usd"]) + usage.cost_usd, 6)
            self._prune()
            self._save()
        self._maybe_warn()
        return usage

    def spent_today(self) -> float:
        with self._lock:
            return round(
                sum(float(b.get("cost_usd", 0.0)) for b in self._today().values()), 6
            )

    def tokens_today(self) -> int:
        with self._lock:
            return sum(
                int(b.get("prompt_tokens", 0)) + int(b.get("completion_tokens", 0))
                for b in self._today().values()
            )

    def check(self) -> None:
        """Raise :class:`BudgetExceeded` once the daily limit is used up."""

        limit = self.daily_limit_usd
        if not limit or limit <= 0:
            return
        spent = self.spent_today()
        if spent >= limit:
            raise BudgetExceeded(
                f"The daily budget of ${limit:.2f} is used up (${spent:.2f} spent today). "
                "Raise JARVIS_BUDGET_DAILY_USD or switch to a local model."
            )

    def _maybe_warn(self) -> None:
        limit = self.daily_limit_usd
        if not limit or limit <= 0 or self._warned:
            return
        spent = self.spent_today()
        if spent >= limit * self.warn_ratio:
            self._warned = True
            LOGGER.warning("Spent $%.2f of the $%.2f daily budget.", spent, limit)

    def report(self, day: str | None = None) -> str:
        """Human-readable summary for one day."""

        key = day or date.today().isoformat()
        with self._lock:
            bucket = dict(self._data.get(key) or {})
        if not bucket:
            return f"No recorded model usage for {key}."
        lines = [f"Model usage for {key}:"]
        total = 0.0
        for provider in sorted(bucket):
            stats = bucket[provider]
            cost = float(stats.get("cost_usd", 0.0))
            total += cost
            lines.append(
                "  {p}: {c} calls, {i} in / {o} out tokens, ${cost:.4f}".format(
                    p=provider,
                    c=stats.get("calls", 0),
                    i=stats.get("prompt_tokens", 0),
                    o=stats.get("completion_tokens", 0),
                    cost=cost,
                )
            )
        lines.append(f"  total: ${total:.4f}")
        if self.daily_limit_usd:
            lines.append(f"  daily limit: ${self.daily_limit_usd:.2f}")
        return "\n".join(lines)


def default_tracker() -> BudgetTracker:
    """Process-wide tracker configured from the environment."""

    with _STATE_LOCK:
        tracker = _STATE.get("tracker")
        if tracker is None:
            raw = os.environ.get("JARVIS_BUDGET_DAILY_USD", "").strip()
            try:
                limit = float(raw) if raw else None
            except ValueError:
                LOGGER.warning("JARVIS_BUDGET_DAILY_USD is not a number; ignoring it")
                limit = None
            tracker = BudgetTracker(
                daily_limit_usd=limit,
                path=os.environ.get("JARVIS_USAGE_LOG") or None,
            )
            _STATE["tracker"] = tracker
        return tracker


def reset_default_tracker() -> None:
    """Drop the cached tracker (used by the tests and after a config reload)."""

    with _STATE_LOCK:
        _STATE.pop("tracker", None)
