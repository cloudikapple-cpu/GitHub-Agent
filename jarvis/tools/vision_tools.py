"""Screen understanding tools."""

from __future__ import annotations

from typing import Any, Callable

from ..vision import VisionError, capture_screen, describe_image, load_image
from .base import Tool


class SeeScreenTool(Tool):
    name = "see_screen"
    description = (
        "Take a screenshot and describe what is on it. Use it when the user "
        "refers to something visible on their display, an error dialog or a UI."
    )
    category = "vision"
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "What to look for, e.g. 'what does the error say?'.",
            }
        },
    }

    def __init__(self, backend_factory: Callable[[], Any], max_width: int = 1280) -> None:
        self._backend_factory = backend_factory
        self.max_width = max_width

    def run(self, question: str = "") -> str:
        try:
            image = capture_screen(self.max_width)
            return describe_image(image, question, self._backend_factory())
        except VisionError as exc:
            return f"Error: {exc}"


class LookAtImageTool(Tool):
    name = "look_at_image"
    description = "Describe or read an image file from disk (screenshot, photo, diagram)."
    category = "vision"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the image file."},
            "question": {"type": "string", "description": "What to look for."},
        },
        "required": ["path"],
    }

    def __init__(self, backend_factory: Callable[[], Any], max_width: int = 1280) -> None:
        self._backend_factory = backend_factory
        self.max_width = max_width

    def run(self, path: str, question: str = "") -> str:
        try:
            image = load_image(path, self.max_width)
            return describe_image(image, question, self._backend_factory())
        except VisionError as exc:
            return f"Error: {exc}"


def build_vision_tools(backend_factory: Callable[[], Any], max_width: int = 1280) -> list[Tool]:
    return [
        SeeScreenTool(backend_factory, max_width),
        LookAtImageTool(backend_factory, max_width),
    ]
