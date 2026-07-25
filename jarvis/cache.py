"""A cache for model replies.

Asking the same question twice should not cost twice. Every request is hashed
together with the model name and the names of the tools that were offered; if
that fingerprint has been answered before, the answer is replayed from a local
SQLite file instead of the network.

Replies that ask for a tool are never cached. Replaying one would replay the
action behind it, and 'delete the folder' is not a sentence worth repeating
from memory.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PATH = "~/.jarvis/cache.db"
#: A day is long enough to help a working session, short enough that an answer
#: about "today" does not quietly become a lie.
DEFAULT_TTL = 24 * 60 * 60
DEFAULT_MAX_ENTRIES = 5000
#: Accepted as a path for tests and throwaway runs.
MEMORY = ":memory:"


def fingerprint(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> str:
    """Return a stable key for one request.

    Only the parts that change the answer take part: the model, the role and
    text of every message, and the set of tool names on offer.
    """

    payload = {
        "model": model,
        "messages": [
            {"role": str(message.get("role") or ""), "content": str(message.get("content") or "")}
            for message in messages
        ],
        "tools": sorted(str(tool.get("name") or "") for tool in (tools or [])),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class CacheStats:
    """What the cache has done so far."""

    entries: int = 0
    hits: int = 0
    misses: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def format(self) -> str:
        return (
            f"{self.entries} cached replies, {self.hits} hits, {self.misses} misses "
            f"({self.hit_rate * 100:.0f}% of requests answered without the network)"
        )


class ResponseCache:
    """Persistent store of model replies, keyed by request fingerprint."""

    def __init__(
        self,
        path: str = DEFAULT_PATH,
        ttl: int = DEFAULT_TTL,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        enabled: bool = True,
    ) -> None:
        self.ttl = max(0, int(ttl))
        self.max_entries = max(0, int(max_entries))
        self.enabled = bool(enabled)
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        if path == MEMORY:
            self.path = MEMORY
        else:
            resolved = Path(path).expanduser()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self.path = str(resolved)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._create_schema()

    # ------------------------------------------------------------------
    def _create_schema(self) -> None:
        with self._lock:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS replies (
                    key TEXT PRIMARY KEY,
                    model TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    created REAL NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._connection.commit()

    # ------------------------------------------------------------------
    def get(self, key: str) -> str | None:
        """Return a fresh cached reply, or ``None``."""

        if not self.enabled:
            return None
        with self._lock:
            row = self._connection.execute(
                "SELECT content, created FROM replies WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                self.misses += 1
                return None
            if self.ttl and time.time() - float(row[1]) > self.ttl:
                self._connection.execute("DELETE FROM replies WHERE key = ?", (key,))
                self._connection.commit()
                self.misses += 1
                return None
            self._connection.execute("UPDATE replies SET used = used + 1 WHERE key = ?", (key,))
            self._connection.commit()
            self.hits += 1
            return str(row[0])

    def set(self, key: str, content: str, model: str = "") -> bool:
        """Remember a reply. Empty answers are not worth keeping."""

        if not self.enabled or not content or not content.strip():
            return False
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO replies (key, model, content, created, used) "
                "VALUES (?, ?, ?, ?, 0)",
                (key, model, content, time.time()),
            )
            self._connection.commit()
        self.prune()
        return True

    # ------------------------------------------------------------------
    def prune(self) -> int:
        """Drop expired rows and anything beyond ``max_entries``."""

        removed = 0
        with self._lock:
            if self.ttl:
                cursor = self._connection.execute(
                    "DELETE FROM replies WHERE created < ?", (time.time() - self.ttl,)
                )
                removed += cursor.rowcount or 0
            if self.max_entries:
                cursor = self._connection.execute(
                    "DELETE FROM replies WHERE key IN ("
                    "SELECT key FROM replies ORDER BY created DESC LIMIT -1 OFFSET ?"
                    ")",
                    (self.max_entries,),
                )
                removed += cursor.rowcount or 0
            self._connection.commit()
        return removed

    def clear(self) -> int:
        with self._lock:
            cursor = self._connection.execute("DELETE FROM replies")
            self._connection.commit()
            return cursor.rowcount or 0

    def count(self) -> int:
        with self._lock:
            return int(self._connection.execute("SELECT COUNT(*) FROM replies").fetchone()[0])

    def stats(self) -> CacheStats:
        return CacheStats(entries=self.count(), hits=self.hits, misses=self.misses)

    def close(self) -> None:
        with self._lock:
            self._connection.close()
