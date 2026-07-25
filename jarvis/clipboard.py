"""Clipboard history.

Windows 11 has its own clipboard history behind ``Win+V``, but the assistant
cannot read it. This keeps a small ring buffer of its own in
``~/.jarvis/clipboard.json`` so that 'what did I copy before this?' has an
answer, and so a skill can act on the last few items.

The daemon runs :class:`ClipboardWatcher` in the background; every tool that
touches the clipboard also records what it saw, so history works even without
the daemon.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LOGGER = logging.getLogger(__name__)

DEFAULT_LIMIT = 50
MAX_ENTRY_CHARS = 10_000
POLL_SECONDS = 2.0

__all__ = [
    "ClipEntry",
    "ClipboardHistory",
    "ClipboardUnavailable",
    "ClipboardWatcher",
    "default_history_path",
    "read_clipboard",
    "write_clipboard",
]


class ClipboardUnavailable(RuntimeError):
    """Raised when no clipboard backend is installed or reachable."""


def default_history_path() -> Path:
    return Path.home() / ".jarvis" / "clipboard.json"


def _backend():
    try:
        import pyperclip
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ClipboardUnavailable(
            "Clipboard access requires the 'pyperclip' package "
            '(pip install "jarvis-desktop[desktop]").'
        ) from exc
    return pyperclip


def read_clipboard() -> str:
    """Current clipboard text."""

    pyperclip = _backend()
    try:
        return pyperclip.paste() or ""
    except Exception as exc:  # noqa: BLE001 - backends differ wildly per OS
        raise ClipboardUnavailable(str(exc)) from exc


def write_clipboard(text: str) -> None:
    """Replace the clipboard contents."""

    pyperclip = _backend()
    try:
        pyperclip.copy(text)
    except Exception as exc:  # noqa: BLE001
        raise ClipboardUnavailable(str(exc)) from exc


@dataclass
class ClipEntry:
    """One remembered clipboard item."""

    text: str
    at: str

    def preview(self, width: int = 80) -> str:
        flat = " ".join(self.text.split())
        if len(flat) <= width:
            return flat
        return flat[: width - 1] + "…"


class ClipboardHistory:
    """A newest-first ring buffer persisted as JSON."""

    def __init__(self, path: Path | str | None = None, limit: int = DEFAULT_LIMIT) -> None:
        self.path = Path(path) if path else default_history_path()
        self.limit = max(1, int(limit))
        self._lock = threading.RLock()

    # -------------------------------------------------------------- storage
    def _load(self) -> list[ClipEntry]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            LOGGER.warning("Clipboard history unreadable (%s); starting a new one.", exc)
            return []
        if not isinstance(raw, list):
            return []
        entries = []
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                entries.append(ClipEntry(text=item["text"], at=str(item.get("at", ""))))
        return entries

    def _save(self, entries: list[ClipEntry]) -> None:
        payload = [{"text": entry.text, "at": entry.at} for entry in entries[: self.limit]]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            LOGGER.warning("Could not write the clipboard history: %s", exc)

    # ---------------------------------------------------------------- public
    def entries(self) -> list[ClipEntry]:
        """Remembered items, newest first."""

        with self._lock:
            return self._load()

    def record(self, text: str) -> bool:
        """Remember a clipboard item. Returns False when it was skipped.

        Empty strings and a repeat of the newest entry are skipped, so polling
        every couple of seconds does not fill the buffer with duplicates.
        """

        if not text or not text.strip():
            return False
        clipped = text[:MAX_ENTRY_CHARS]
        with self._lock:
            entries = self._load()
            if entries and entries[0].text == clipped:
                return False
            entries = [entry for entry in entries if entry.text != clipped]
            entries.insert(0, ClipEntry(text=clipped, at=datetime.now().isoformat(timespec="seconds")))
            self._save(entries)
        return True

    def clear(self) -> int:
        """Forget everything. Returns how many items were removed."""

        with self._lock:
            removed = len(self._load())
            self._save([])
        return removed

    def format(self, limit: int = 10) -> str:
        """Human-readable listing for the tool output."""

        entries = self.entries()[: max(1, limit)]
        if not entries:
            return "The clipboard history is empty."
        lines = [f"{index}. [{entry.at}] {entry.preview()}" for index, entry in enumerate(entries, 1)]
        return "\n".join(lines)


class ClipboardWatcher:
    """Poll the clipboard and record every change.

    Polling is the only portable option: Windows clipboard notifications need a
    window and a message loop, and two seconds is invisible to the user while
    costing nothing measurable.
    """

    def __init__(
        self,
        history: ClipboardHistory | None = None,
        interval: float = POLL_SECONDS,
    ) -> None:
        self.history = history or ClipboardHistory()
        self.interval = max(0.2, float(interval))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> bool:
        """Start watching. Returns False when no clipboard backend exists."""

        if self._thread is not None:
            return True
        try:
            read_clipboard()
        except ClipboardUnavailable as exc:
            LOGGER.info("Clipboard history disabled: %s", exc)
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="jarvis-clipboard", daemon=True)
        self._thread.start()
        return True

    def _loop(self) -> None:
        previous = ""
        while not self._stop.is_set():
            try:
                current = read_clipboard()
            except ClipboardUnavailable as exc:
                LOGGER.debug("Clipboard read failed: %s", exc)
                current = previous
            if current and current != previous:
                previous = current
                self.history.record(current)
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.interval + 1.0)


def _sleep(seconds: float) -> None:  # pragma: no cover - kept for tests to patch
    time.sleep(seconds)
