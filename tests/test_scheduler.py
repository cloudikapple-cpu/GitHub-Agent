"""Reminders and scheduled tasks."""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from jarvis.scheduler import Job, ScheduleError, Scheduler, parse_duration, parse_when


def test_parse_duration_understands_units_and_russian():
    assert parse_duration("45s") == 45
    assert parse_duration("15m") == 900
    assert parse_duration("2h") == 7200
    assert parse_duration("3дн") == 259200
    assert parse_duration("10") == 600


def test_parse_when_accepts_relative_and_absolute_times():
    now = datetime(2026, 7, 25, 9, 0, 0)
    assert parse_when("in 30m", now) == (now.timestamp() + 1800)
    assert parse_when("через 2 час", now) == (now.timestamp() + 7200)
    assert parse_when("2026-07-25 18:30") > 0


def test_parse_when_rejects_nonsense():
    with pytest.raises(ScheduleError):
        parse_when("whenever")


def test_jobs_persist_between_instances(tmp_path):
    path = str(tmp_path / "jobs.json")
    scheduler = Scheduler(path=path)
    scheduler.add("drink water", every="1h")
    assert len(Scheduler(path=path).list()) == 1


def test_due_jobs_fire_once_and_one_shots_disable_themselves(tmp_path):
    scheduler = Scheduler(path=str(tmp_path / "jobs.json"))
    job = scheduler.add("stand up", when="in 1s")
    job.next_run = time.time() - 1

    fired: list[Job] = []
    assert scheduler.run_pending(fired.append) == 1
    assert [item.text for item in fired] == ["stand up"]
    assert scheduler.jobs[job.id].enabled is False
    assert scheduler.run_pending(fired.append) == 0


def test_interval_jobs_reschedule_themselves(tmp_path):
    scheduler = Scheduler(path=str(tmp_path / "jobs.json"))
    job = scheduler.add("backup", every="30m")
    job.next_run = time.time() - 1
    scheduler.run_pending(lambda _job: None)
    assert scheduler.jobs[job.id].enabled is True
    assert scheduler.jobs[job.id].next_run > time.time()


def test_a_failing_handler_does_not_break_the_loop(tmp_path):
    scheduler = Scheduler(path=str(tmp_path / "jobs.json"))
    job = scheduler.add("boom", when="in 1s")
    job.next_run = time.time() - 1

    def handler(_job):
        raise RuntimeError("handler exploded")

    assert scheduler.run_pending(handler) == 1
