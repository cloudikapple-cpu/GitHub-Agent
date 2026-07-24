"""Example Python skill.

Every ``.py`` file in a skills directory is imported at startup. Define a
``register(registry, config)`` function (or a module-level ``TOOLS`` list) and
your tools become available to the model immediately.

Skills run with your user privileges — only install ones you trust.
"""

from __future__ import annotations

import datetime as _dt

from jarvis.tools.base import FunctionTool


def _workday_summary(days: int = 1) -> str:
    today = _dt.date.today()
    start = today - _dt.timedelta(days=max(int(days), 1) - 1)
    return f"Summarise everything I worked on between {start} and {today}."


def register(registry, config) -> None:
    registry.register(
        FunctionTool(
            name="workday_summary",
            description=(
                "Return instructions for summarising the user's recent work. "
                "Example of a custom skill."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "How many days back to cover (default 1).",
                        "default": 1,
                    }
                },
            },
            func=_workday_summary,
        )
    )
