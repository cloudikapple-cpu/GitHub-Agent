"""Let the assistant look at the screen.

A screenshot is captured, downscaled, encoded as base64 PNG and sent to a
vision-capable model together with a question.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path


class VisionError(RuntimeError):
    """Raised when a screenshot cannot be taken or described."""


def capture_screen(max_width: int = 1280) -> bytes:
    """Return a PNG screenshot of the primary display."""

    try:
        import pyautogui
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise VisionError(
            "Screen capture needs the desktop extra: pip install 'jarvis-desktop[desktop]'"
        ) from exc

    image = pyautogui.screenshot()
    if max_width and image.width > max_width:
        height = int(image.height * max_width / image.width)
        image = image.resize((max_width, height))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def encode_image(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def load_image(path: str, max_width: int = 1280) -> bytes:
    """Read an image file, downscaling it when it is very large."""

    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise VisionError(f"No such image: {file_path}")
    raw = file_path.read_bytes()
    try:
        from PIL import Image
    except ImportError:
        return raw
    image = Image.open(io.BytesIO(raw))
    if max_width and image.width > max_width:
        height = int(image.height * max_width / image.width)
        image = image.resize((max_width, height))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()
    return raw


def describe_image(
    image_bytes: bytes,
    question: str,
    backend,
) -> str:
    """Ask ``backend`` what is in the image."""

    messages = [
        {
            "role": "user",
            "content": question or "Describe what you see and any actionable detail.",
            "images": [encode_image(image_bytes)],
        }
    ]
    response = backend.chat(messages)
    return (response.content or "").strip() or "The model returned no description."
