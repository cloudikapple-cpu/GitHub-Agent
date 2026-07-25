"""Long-term semantic memory.

Everything worth remembering — facts about the user, project decisions,
session summaries — lands in a local SQLite file and can be recalled by
meaning rather than by exact wording.

Embeddings come from an OpenAI-compatible ``/embeddings`` endpoint when a
provider is configured. Without one, a deterministic hashing embedding is used:
lower quality, but zero dependencies, fully offline, and good enough to find
related notes.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

HASH_DIMENSIONS = 512


@dataclass
class Note:
    """A single remembered item."""

    id: int
    text: str
    tags: list[str]
    source: str
    created: float
    score: float = 0.0

    def format(self) -> str:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.created))
        tags = f" [{', '.join(self.tags)}]" if self.tags else ""
        return f"#{self.id} ({stamp}){tags}: {self.text}"


def hash_embedding(text: str, dimensions: int = HASH_DIMENSIONS) -> list[float]:
    """Offline bag-of-words embedding based on hashed tokens."""

    vector = [0.0] * dimensions
    tokens = [token for token in "".join(
        char.lower() if char.isalnum() else " " for char in text
    ).split() if token]
    for token in tokens:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    a_list, b_list = list(a), list(b)
    if len(a_list) != len(b_list) or not a_list:
        return 0.0
    dot = sum(x * y for x, y in zip(a_list, b_list, strict=True))
    na = math.sqrt(sum(x * x for x in a_list))
    nb = math.sqrt(sum(y * y for y in b_list))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


class KnowledgeBase:
    """SQLite-backed vector store for durable notes."""

    def __init__(
        self,
        path: str = "~/.jarvis/knowledge.db",
        embedder: Any | None = None,
        top_k: int = 5,
    ) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.top_k = top_k
        #: Callable[[str], list[float]]; defaults to the offline hashing embedder.
        self.embedder = embedder or hash_embedding
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._create_schema()

    # ------------------------------------------------------------------
    def _create_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL DEFAULT '',
                created REAL NOT NULL,
                embedding TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def _embed(self, text: str) -> list[float]:
        try:
            vector = self.embedder(text)
        except Exception:  # noqa: BLE001 - never lose a note over embeddings
            vector = hash_embedding(text)
        return [float(value) for value in vector]

    # ------------------------------------------------------------------
    def add(self, text: str, tags: list[str] | None = None, source: str = "") -> int:
        """Store a note and return its id."""

        text = text.strip()
        if not text:
            raise ValueError("Cannot remember an empty note.")
        cursor = self._connection.execute(
            "INSERT INTO notes (text, tags, source, created, embedding) VALUES (?, ?, ?, ?, ?)",
            (
                text,
                json.dumps(tags or [], ensure_ascii=False),
                source,
                time.time(),
                json.dumps(self._embed(text)),
            ),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    def search(self, query: str, limit: int | None = None, tag: str = "") -> list[Note]:
        """Return the notes closest in meaning to ``query``."""

        rows = self._connection.execute(
            "SELECT id, text, tags, source, created, embedding FROM notes"
        ).fetchall()
        if not rows:
            return []

        query_vector = self._embed(query)
        scored: list[Note] = []
        for row in rows:
            tags = json.loads(row[2] or "[]")
            if tag and tag not in tags:
                continue
            note = Note(
                id=int(row[0]),
                text=row[1],
                tags=tags,
                source=row[3],
                created=float(row[4]),
                score=cosine(query_vector, json.loads(row[5])),
            )
            scored.append(note)

        scored.sort(key=lambda note: note.score, reverse=True)
        return scored[: (limit or self.top_k)]

    def recent(self, limit: int = 10) -> list[Note]:
        rows = self._connection.execute(
            "SELECT id, text, tags, source, created FROM notes ORDER BY created DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            Note(
                id=int(row[0]),
                text=row[1],
                tags=json.loads(row[2] or "[]"),
                source=row[3],
                created=float(row[4]),
            )
            for row in rows
        ]

    def forget(self, note_id: int) -> bool:
        cursor = self._connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._connection.commit()
        return cursor.rowcount > 0

    def count(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0])

    def close(self) -> None:
        self._connection.close()


def build_embedder(config) -> Any:
    """Return an embedding callable for ``config.knowledge``.

    Falls back to the offline hashing embedder when no embedding provider is
    configured or the endpoint is unreachable.
    """

    name = getattr(config.knowledge, "embedding_provider", "")
    if not name:
        return hash_embedding

    try:
        provider = config.provider(name)
    except ValueError:
        return hash_embedding

    import requests

    base_url = (provider.base_url or "https://api.openai.com/v1").rstrip("/")
    model = config.knowledge.embedding_model

    def embed(text: str) -> list[float]:
        headers = {"Content-Type": "application/json", **provider.headers}
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"
        response = requests.post(
            f"{base_url}/embeddings",
            json={"model": model, "input": text},
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]

    return embed
