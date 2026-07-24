"""Reminders and scheduled tasks exposed to the model."""

from __future__ import annotations

from typing import Any

from ..scheduler import ScheduleError, Scheduler
from .base import Tool

_WHEN_HELP = "'in 15m', '09:30', '2026-07-25 09:30'"


class RemindTool(Tool):
    name = "remind_me"
    description = (
        "Set a reminder. It pops up as a desktop notification (and is spoken "
        f"when voice is on). Times: {_WHEN_HELP}; repeats: every='30m' or daily_at='09:00'."
    )
    category = "scheduler"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "What to remind about."},
            "when": {"type": "string", "description": f"One-off time: {_WHEN_HELP}."},
            "every": {"type": "string", "description": "Repeat interval, e.g. '30m', '2h'."},
            "daily_at": {"type": "string", "description": "Daily time, e.g. '09:00'."},
            "weekdays": {
                "type": "array",
                "items": {"type": "string"},
                "description": "With daily_at: limit to weekdays, e.g. ['mon','fri'].",
            },
        },
        "required": ["text"],
    }

    def __init__(self, scheduler: Scheduler) -> None:
        self.scheduler = scheduler

    def run(
        self,
        text: str,
        when: str = "",
        every: str = "",
        daily_at: str = "",
        weekdays: list[str] | None = None,
    ) -> str:
        try:
            job = self.scheduler.add(
                text=text,
                when=when,
                every=every,
                daily_at=daily_at,
                weekdays=weekdays,
                kind="reminder",
            )
        except ScheduleError as exc:
            return f"Error: {exc}"
        return f"Reminder set — {job.describe()}"


class ScheduleTaskTool(Tool):
    name = "schedule_task"
    description = (
        "Schedule a prompt for the assistant to run unattended later — for "
        "example a daily report or a nightly backup script."
    )
    category = "scheduler"
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The instruction to execute later."},
            "when": {"type": "string", "description": f"One-off time: {_WHEN_HELP}."},
            "every": {"type": "string", "description": "Repeat interval, e.g. '6h'."},
            "daily_at": {"type": "string", "description": "Daily time, e.g. '20:00'."},
        },
        "required": ["prompt"],
    }

    def __init__(self, scheduler: Scheduler) -> None:
        self.scheduler = scheduler

    def run(self, prompt: str, when: str = "", every: str = "", daily_at: str = "") -> str:
        try:
            job = self.scheduler.add(
                text=prompt, when=when, every=every, daily_at=daily_at, kind="task"
            )
        except ScheduleError as exc:
            return f"Error: {exc}"
        return f"Task scheduled — {job.describe()}"


class ListJobsTool(Tool):
    name = "list_jobs"
    description = "List reminders and scheduled tasks with their next run time."
    category = "scheduler"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, scheduler: Scheduler) -> None:
        self.scheduler = scheduler

    def run(self) -> str:
        jobs = self.scheduler.list()
        if not jobs:
            return "No reminders or scheduled tasks."
        return "\n".join(job.describe() for job in jobs)


class CancelJobTool(Tool):
    name = "cancel_job"
    description = "Cancel a reminder or scheduled task by its id (from list_jobs)."
    category = "scheduler"
    parameters = {
        "type": "object",
        "properties": {"job_id": {"type": "string", "description": "Job id, e.g. 'job2'."}},
        "required": ["job_id"],
    }

    def __init__(self, scheduler: Scheduler) -> None:
        self.scheduler = scheduler

    def run(self, job_id: str) -> str:
        return f"Cancelled {job_id}." if self.scheduler.remove(job_id) else f"No job '{job_id}'."


def build_scheduler_tools(scheduler: Scheduler) -> list[Any]:
    return [
        RemindTool(scheduler),
        ScheduleTaskTool(scheduler),
        ListJobsTool(scheduler),
        CancelJobTool(scheduler),
    ]
