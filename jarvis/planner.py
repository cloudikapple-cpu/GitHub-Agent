"""Two-level planning: think cheaply, act expensively.

A long request answered in one pass tends to wander. Here a first, cheap call
turns the request into a short list of concrete steps, and the plan is handed
to the agent as context before it starts calling tools. The planning model can
be a different, smaller provider -- that is the point of ``planner.provider``.

Planning never blocks a run: if the planning model is unreachable or answers
with nonsense, the plan is simply empty and the agent proceeds as before.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

LOGGER = logging.getLogger(__name__)

PLAN_SYSTEM_PROMPT = """You are the planning half of a desktop assistant.

Turn the user's request into a short, ordered list of concrete steps that
another agent will carry out with tools (web search, files, shell, code,
desktop control).

Rules:
- 2 to 6 steps, one line each, in the order they must happen.
- Each step is an action, not a thought: name what to do and to what.
- No preamble, no numbering commentary, no closing remarks.
- If the request is a simple question, answer with the single step "Answer directly".
"""

#: Requests shorter than this are not worth a planning round-trip.
DEFAULT_MIN_CHARS = 280
DEFAULT_MAX_STEPS = 6
#: Recognised list markers: "1.", "1)", "-", "*", "•".
_BULLET = re.compile(r"^\s*(?:\d+[.)]|[-*\u2022])\s+")
#: The plan is a means, not an answer: this single step means "just do it".
DIRECT_ANSWER = "answer directly"


def parse_plan(text: str, max_steps: int = DEFAULT_MAX_STEPS) -> list[str]:
    """Pull an ordered list of steps out of whatever the model replied."""

    if not text or not text.strip():
        return []

    stripped = text.strip()
    # Some models answer with a JSON array even when asked for lines.
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            steps = [str(item).strip() for item in parsed if str(item).strip()]
            return steps[:max_steps]

    steps: list[str] = []
    for raw in stripped.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _BULLET.match(line):
            line = _BULLET.sub("", line).strip()
        elif steps:
            # Unmarked line after a list: a continuation, not a new step.
            continue
        if not line or line.endswith(":"):
            continue
        steps.append(line)
        if len(steps) >= max_steps:
            break
    return steps


def format_plan(steps: list[str]) -> str:
    """Render a plan for the executing agent."""

    if not steps:
        return ""
    body = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    return (
        "Draft plan for this request (adjust it if reality disagrees):\n"
        f"{body}"
    )


class Planner:
    """Ask a model for a plan before the expensive model starts working."""

    def __init__(
        self,
        backend: Any,
        max_steps: int = DEFAULT_MAX_STEPS,
        min_chars: int = DEFAULT_MIN_CHARS,
    ) -> None:
        self.backend = backend
        self.max_steps = max_steps
        self.min_chars = min_chars

    def should_plan(self, task: str) -> bool:
        """Long or multi-part requests earn a plan; one-liners do not."""

        text = task.strip()
        if len(text) >= self.min_chars:
            return True
        markers = (" then ", " and then ", "после чего", ", затем", " затем ", "\n-", "\n1.")
        return any(marker in text.lower() for marker in markers)

    def plan(self, task: str) -> list[str]:
        """Return the steps, or an empty list if planning did not work out."""

        if not task.strip():
            return []
        messages = [
            {"role": "system", "content": PLAN_SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        try:
            response = self.backend.chat(messages)
        except Exception as exc:  # noqa: BLE001 - planning is optional by design
            LOGGER.warning("Planning failed, continuing without a plan: %s", exc)
            return []
        steps = parse_plan(getattr(response, "content", "") or "", self.max_steps)
        if len(steps) == 1 and steps[0].strip().lower().rstrip(".") == DIRECT_ANSWER:
            return []
        return steps

    def context(self, task: str) -> str:
        """Plan ``task`` and render it, or return an empty string."""

        if not self.should_plan(task):
            return ""
        return format_plan(self.plan(task))
