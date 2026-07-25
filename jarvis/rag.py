"""Retrieval over local documents.

:mod:`jarvis.knowledge` remembers what the assistant was *told*. This module
remembers what the user has *written*: notes, specs, source files, exported
chats. Point it at a folder, and the relevant paragraphs are attached to the
prompt automatically instead of being pasted by hand.

Files are split into overlapping chunks, embedded with the same embedder as the
knowledge base (offline hashing by default, a real embedding endpoint when one
is configured) and stored in SQLite. Re-indexing is cheap: a file whose
modification time has not changed is skipped.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .knowledge import cosine, hash_embedding

DEFAULT_PATH = "~/.jarvis/documents.db"
#: Only text-shaped files are worth embedding.
TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".rst",
        ".org",
        ".py",
        ".pyi",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".kt",
        ".go",
        ".rs",
        ".c",
        ".h",
        ".cpp",
        ".cs",
        ".sql",
        ".sh",
        ".ps1",
        ".bat",
        ".ini",
        ".cfg",
        ".conf",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".csv",
        ".html",
        ".css",
        ".tex",
    }
)
#: Folders that are never worth walking into.
SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".idea",
        ".vscode",
        "site-packages",
    }
)
#: Anything larger is a database, a log or a mistake -- not a document.
MAX_FILE_BYTES = 2_000_000
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 150


@dataclass
class Chunk:
    """A retrieved passage."""

    id: int
    path: str
    ordinal: int
    text: str
    score: float = 0.0

    def format(self, width: int = 600) -> str:
        body = self.text if len(self.text) <= width else self.text[:width].rstrip() + "..."
        return f"{self.path} (part {self.ordinal + 1}):\n{body}"


def chunk_text(
    text: str,
    size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """Split text into overlapping pieces, preferring paragraph boundaries."""

    text = text.strip()
    if not text:
        return []
    size = max(200, int(size))
    overlap = max(0, min(int(overlap), size // 2))

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            # Prefer to cut at a blank line, then at a newline, then anywhere.
            window = text[start:end]
            for separator in ("\n\n", "\n", ". "):
                cut = window.rfind(separator)
                if cut > size // 2:
                    end = start + cut + len(separator)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def is_text_file(path: Path, suffixes: frozenset[str] | set[str] | None = None) -> bool:
    allowed = suffixes if suffixes is not None else TEXT_SUFFIXES
    return path.suffix.lower() in allowed


class DocumentIndex:
    """SQLite-backed chunk store with semantic search."""

    def __init__(
        self,
        path: str = DEFAULT_PATH,
        embedder: Any | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_OVERLAP,
        top_k: int = 4,
    ) -> None:
        self.path = ":memory:" if path == ":memory:" else str(Path(path).expanduser())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or hash_embedding
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.top_k = top_k
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._create_schema()

    # ------------------------------------------------------------------
    def _create_schema(self) -> None:
        with self._lock:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    indexed REAL NOT NULL,
                    embedding TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS chunks_by_path ON chunks (path)"
            )
            self._connection.commit()

    def _embed(self, text: str) -> list[float]:
        try:
            vector = self.embedder(text)
        except Exception:  # noqa: BLE001 - a document must never be lost to embeddings
            vector = hash_embedding(text)
        return [float(value) for value in vector]

    # ------------------------------------------------------------------
    def known_mtime(self, path: str) -> float | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT mtime FROM chunks WHERE path = ? LIMIT 1", (path,)
            ).fetchone()
        return float(row[0]) if row else None

    def forget_file(self, path: str) -> int:
        with self._lock:
            cursor = self._connection.execute("DELETE FROM chunks WHERE path = ?", (path,))
            self._connection.commit()
            return cursor.rowcount or 0

    def index_file(self, file: str | Path, force: bool = False) -> int:
        """Index one file; return the number of chunks stored (0 when skipped)."""

        target = Path(file).expanduser()
        if not target.is_file():
            return 0
        stat = target.stat()
        if stat.st_size > MAX_FILE_BYTES:
            return 0
        key = str(target.resolve())
        if not force and self.known_mtime(key) == stat.st_mtime:
            return 0

        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 0
        pieces = chunk_text(text, self.chunk_size, self.overlap)
        self.forget_file(key)
        if not pieces:
            return 0

        now = time.time()
        rows = [
            (key, ordinal, piece, stat.st_mtime, now, json.dumps(self._embed(piece)))
            for ordinal, piece in enumerate(pieces)
        ]
        with self._lock:
            self._connection.executemany(
                "INSERT INTO chunks (path, ordinal, text, mtime, indexed, embedding) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._connection.commit()
        return len(rows)

    def index_path(
        self,
        root: str | Path,
        suffixes: set[str] | None = None,
        max_files: int = 2000,
        force: bool = False,
    ) -> dict[str, int]:
        """Index a file or a whole folder tree. Returns a small report."""

        target = Path(root).expanduser()
        report = {"files": 0, "chunks": 0, "skipped": 0}
        if target.is_file():
            chunks = self.index_file(target, force=force)
            report["files"] += 1 if chunks else 0
            report["chunks"] += chunks
            report["skipped"] += 0 if chunks else 1
            return report
        if not target.is_dir():
            return report

        allowed = frozenset(suffixes) if suffixes else TEXT_SUFFIXES
        seen = 0
        for candidate in sorted(target.rglob("*")):
            if seen >= max_files:
                break
            if candidate.is_dir():
                continue
            if any(part in SKIP_DIRECTORIES or part.startswith(".") for part in candidate.parts[:-1]):
                continue
            if not is_text_file(candidate, allowed):
                continue
            seen += 1
            chunks = self.index_file(candidate, force=force)
            if chunks:
                report["files"] += 1
                report["chunks"] += chunks
            else:
                report["skipped"] += 1
        return report

    # ------------------------------------------------------------------
    def search(self, query: str, limit: int | None = None, min_score: float = 0.0) -> list[Chunk]:
        """Return the passages closest in meaning to ``query``."""

        if not query.strip():
            return []
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, path, ordinal, text, embedding FROM chunks"
            ).fetchall()
        if not rows:
            return []

        vector = self._embed(query)
        scored = [
            Chunk(
                id=int(row[0]),
                path=str(row[1]),
                ordinal=int(row[2]),
                text=str(row[3]),
                score=cosine(vector, json.loads(row[4])),
            )
            for row in rows
        ]
        scored = [chunk for chunk in scored if chunk.score >= min_score]
        scored.sort(key=lambda chunk: chunk.score, reverse=True)
        return scored[: (limit or self.top_k)]

    # ------------------------------------------------------------------
    def stats(self) -> dict[str, int]:
        with self._lock:
            chunks = int(self._connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
            files = int(
                self._connection.execute("SELECT COUNT(DISTINCT path) FROM chunks").fetchone()[0]
            )
        return {"files": files, "chunks": chunks}

    def paths(self) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT DISTINCT path FROM chunks ORDER BY path"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def clear(self) -> int:
        with self._lock:
            cursor = self._connection.execute("DELETE FROM chunks")
            self._connection.commit()
            return cursor.rowcount or 0

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def format_context(chunks: list[Chunk], width: int = 600) -> str:
    """Render retrieved passages for the prompt."""

    if not chunks:
        return ""
    body = "\n\n".join(chunk.format(width) for chunk in chunks)
    return f"Relevant passages from the user's documents:\n{body}"
