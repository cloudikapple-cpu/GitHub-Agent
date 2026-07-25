"""Reminders and scheduled tasks.

A job either *reminds* you (a desktop notification, optionally spoken) or
*runs a prompt* through the assistant unattended. Jobs are stored as JSON, so
they survive restarts.

Supported schedules:

* ``once``     — at an absolute time (``2026-07-25 09:30`` or ``in 15m``);
* ``interval`` — every N seconds/minutes/hours;
* ``daily``    — every day at ``HH:MM``;
* ``weekly``   — on given weekdays at ``HH:MM``.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

WEEKDAYS = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6,
}

_RELATIVE = re.compile(r"^(?:in|через)\s+(\d+)\s*([smhd]|сек|мин|час|дн)", re.I)
_DURATION = re.compile(r"^(\d+)\s*([smhd]|сек|мин|час|дн)?$", re.I)

_UNIT_SECONDS = {
    "s": 1, "сек": 1,
    "m": 60, "мин": 60,
    "h": 3600, "час": 3600,
    "d": 86400, "дн": 86400,
}


class ScheduleError(ValueError):
    """Raised when a schedule cannot be understood."""


def parse_duration(text: str) -> int:
    """Turn ``"15m"``, ``"2 час"`` or ``"90"`` into seconds."""

    match = _DURATION.match(str(text).strip())
    if not match:
        raise ScheduleError(f"Cannot read duration '{text}'.")
    amount = int(match.group(1))
    unit = (match.group(2) or "m").lower()
    return amount * _UNIT_SECONDS.get(unit, 60)


def parse_when(text: str, now: datetime | None = None) -> float:
    """Turn a human time into a POSIX timestamp."""

    now = now or datetime.now()
    raw = str(text).strip()

    relative = _RELATIVE.match(raw)
    if relative:
        seconds = int(relative.group(1)) * _UNIT_SECONDS.get(relative.group(2).lower(), 60)
        return (now + timedelta(seconds=seconds)).timestamp()

    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%H:%M"):
        try:
            parsed = datetime.strptime(raw, pattern)
        except ValueError:
            continue
        if pattern == "%H:%M":
            parsed = now.replace(
                hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
            )
            if parsed <= now:
                parsed += timedelta(days=1)
        return parsed.timestamp()

    raise ScheduleError(
        f"Cannot read time '{text}'. Use 'in 15m', '09:30' or '2026-07-25 09:30'."
    )


@dataclass
class Job:
    """A reminder or an unattended task."""

    id: str
    #: ``reminder`` shows a notification, ``task`` runs ``prompt`` through the agent.
    kind: str = "reminder"
    text: str = ""
    #: ``once``, ``interval``, ``daily`` or ``weekly``.
    schedule: str = "once"
    next_run: float = 0.0
    interval_seconds: int = 0
    at: str = ""
    weekdays: list[int] = field(default_factory=list)
    enabled: bool = True
    last_run: float = 0.0
    runs: int = 0

    def due(self, now: float | None = None) -> bool:
        return self.enabled and self.next_run and (now or time.time()) >= self.next_run

    def reschedule(self, now: float | None = None) -> None:
        """Move ``next_run`` forward; disable one-shot jobs."""

        moment = datetime.fromtimestamp(now or time.time())
        self.last_run = moment.timestamp()
        self.runs += 1

        if self.schedule == "interval" and self.interval_seconds > 0:
            self.next_run = moment.timestamp() + self.interval_seconds
            return
        if self.schedule in {"daily", "weekly"} and self.at:
            hour, _, minute = self.at.partition(":")
            candidate = moment.replace(
                hour=int(hour), minute=int(minute or 0), second=0, microsecond=0
            )
            for _ in range(8):
                candidate += timedelta(days=1)
                if self.schedule == "daily" or candidate.weekday() in self.weekdays:
                    self.next_run = candidate.timestamp()
                    return
        self.enabled = False
        self.next_run = 0.0

    def describe(self) -> str:
        when = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(self.next_run))
            if self.next_run
            else "—"
        )
        state = "on" if self.enabled else "off"
        return f"{self.id} [{self.kind}/{self.schedule}, {state}] next {when}: {self.text}"


class Scheduler:
    """Persistent job store with a background loop."""

    def __init__(self, path: str = "~/.jarvis/jobs.json", tick_seconds: int = 20) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tick_seconds = max(1, tick_seconds)
        self.jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        with self._lock:
            self.jobs = {
                str(item.get("id")): Job(**item)
                for item in raw
                if isinstance(item, dict) and item.get("id")
            }

    def save(self) -> None:
        with self._lock:
            payload = [asdict(job) for job in self.jobs.values()]
        try:
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    # ------------------------------------------------------------------
    def _next_id(self) -> str:
        index = 1
        while f"job{index}" in self.jobs:
            index += 1
        return f"job{index}"

    def add(
        self,
        text: str,
        when: str = "",
        every: str = "",
        daily_at: str = "",
        weekdays: list[str] | None = None,
        kind: str = "reminder",
    ) -> Job:
        """Create a job. Exactly one of ``when``/``every``/``daily_at`` is used."""

        with self._lock:
            job = Job(id=self._next_id(), kind=kind, text=text)

            if every:
                job.schedule = "interval"
                job.interval_seconds = parse_duration(every)
                job.next_run = time.time() + job.interval_seconds
            elif daily_at:
                job.at = daily_at
                job.next_run = parse_when(daily_at)
                if weekdays:
                    job.schedule = "weekly"
                    job.weekdays = sorted(
                        WEEKDAYS[day.lower()[:3]] if day.lower()[:3] in WEEKDAYS else int(day)
                        for day in weekdays
                    )
                else:
                    job.schedule = "daily"
            elif when:
                job.schedule = "once"
                job.next_run = parse_when(when)
            else:
                raise ScheduleError("Provide 'when', 'every' or 'daily_at'.")

            self.jobs[job.id] = job
        self.save()
        return job

    def remove(self, job_id: str) -> bool:
        with self._lock:
            removed = self.jobs.pop(job_id, None) is not None
        if removed:
            self.save()
        return removed

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self.jobs.values(), key=lambda job: job.next_run or float("inf"))

    def due(self, now: float | None = None) -> list[Job]:
        moment = now or time.time()
        with self._lock:
            return [job for job in self.jobs.values() if job.due(moment)]

    # ------------------------------------------------------------------
    def run_pending(self, handler: Callable[[Job], Any]) -> int:
        """Fire every due job through ``handler`` and reschedule it."""

        fired = 0
        for job in self.due():
            try:
                handler(job)
            except Exception:  # noqa: BLE001 - a bad job must not kill the loop
                pass
            job.reschedule()
            fired += 1
        if fired:
            self.save()
        return fired

    def start(self, handler: Callable[[Job], Any]) -> None:
        """Run the scheduler loop in a daemon thread."""

        if self._thread and self._thread.is_alive():
            return

        def loop() -> None:
            while not self._stop.wait(self.tick_seconds):
                self.run_pending(handler)

        self._stop.clear()
        self._thread = threading.Thread(target=loop, name="jarvis-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
