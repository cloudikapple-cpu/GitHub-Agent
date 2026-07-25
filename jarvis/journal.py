"""Undo journal for destructive filesystem actions.

Jarvis can delete, overwrite and move real files. A single misunderstood
instruction should not be unrecoverable, so every destructive tool records what
it is about to do:

* **delete** — the target is *moved* into ``~/.jarvis/trash`` instead of being
  destroyed, and the backup location is written to the journal;
* **write** — an existing file is copied aside before it is overwritten (a
  brand new file is journalled with ``backup: null`` so undo simply removes it);
* **move** — the source and destination are recorded so the move can be
  reversed.

The journal itself is a JSONL file: one entry per line, newest last. Undo pops
the last entry, reverses it, and rewrites the file. This keeps the format
trivial to inspect by hand — which matters when something has gone wrong.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

#: Where the journal and the trash live by default.
DEFAULT_JOURNAL = Path.home() / ".jarvis" / "journal.jsonl"
DEFAULT_TRASH = Path.home() / ".jarvis" / "trash"

#: Older entries are dropped so the journal cannot grow without bound.
MAX_ENTRIES = 500


class JournalError(RuntimeError):
    """Raised when an action cannot be recorded or reversed."""


class Journal:
    """Append-only record of destructive actions, with a single-step undo."""

    def __init__(
        self,
        path: str | Path | None = None,
        trash: str | Path | None = None,
    ):
        self.path = Path(path).expanduser() if path else DEFAULT_JOURNAL
        self.trash = Path(trash).expanduser() if trash else DEFAULT_TRASH

    # ------------------------------------------------------------------
    # storage
    # ------------------------------------------------------------------
    def entries(self) -> list[dict]:
        """Return every journal entry, oldest first. Broken lines are skipped."""

        if not self.path.is_file():
            return []
        records: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def _write_all(self, records: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        self.path.write_text(payload, encoding="utf-8")

    def _append(self, record: dict) -> None:
        record["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        records = self.entries()
        records.append(record)
        if len(records) > MAX_ENTRIES:
            records = records[-MAX_ENTRIES:]
        self._write_all(records)

    # ------------------------------------------------------------------
    # backups
    # ------------------------------------------------------------------
    def _backup_path(self, source: Path) -> Path:
        self.trash.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return self.trash / f"{stamp}_{uuid.uuid4().hex[:8]}_{source.name}"

    def _stash(self, source: Path) -> Path:
        """Move ``source`` into the trash and return its new location."""

        backup = self._backup_path(source)
        shutil.move(str(source), str(backup))
        return backup

    def _copy_aside(self, source: Path) -> Path:
        """Copy ``source`` into the trash, leaving the original in place."""

        backup = self._backup_path(source)
        if source.is_dir():
            shutil.copytree(source, backup)
        else:
            shutil.copy2(source, backup)
        return backup

    # ------------------------------------------------------------------
    # recording
    # ------------------------------------------------------------------
    def record_delete(self, path: Path) -> Path:
        """Move ``path`` to the trash instead of deleting it."""

        backup = self._stash(path)
        self._append({"op": "delete", "path": str(path), "backup": str(backup)})
        return backup

    def record_write(self, path: Path) -> Path | None:
        """Back up ``path`` before it is written. Returns the backup, if any."""

        backup = self._copy_aside(path) if path.exists() else None
        self._append(
            {
                "op": "write",
                "path": str(path),
                "backup": str(backup) if backup else None,
            }
        )
        return backup

    def record_move(self, source: Path, destination: Path) -> None:
        """Record a completed move so it can be reversed."""

        self._append(
            {"op": "move", "source": str(source), "destination": str(destination)}
        )

    # ------------------------------------------------------------------
    # undo
    # ------------------------------------------------------------------
    def undo_last(self) -> str:
        """Reverse the most recent recorded action and drop it from the log."""

        records = self.entries()
        if not records:
            return "Nothing to undo: the journal is empty."

        entry = records[-1]
        try:
            message = self._reverse(entry)
        except (OSError, JournalError) as exc:
            return f"Could not undo {entry.get('op', 'action')}: {exc}"

        self._write_all(records[:-1])
        return message

    def _reverse(self, entry: dict) -> str:
        op = entry.get("op")

        if op == "delete":
            target = Path(entry["path"])
            backup = Path(entry["backup"])
            if not backup.exists():
                raise JournalError(f"the backup '{backup}' is gone")
            if target.exists():
                raise JournalError(f"'{target}' exists again; remove it first")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup), str(target))
            return f"Restored {target} from the trash."

        if op == "write":
            target = Path(entry["path"])
            backup = entry.get("backup")
            if backup is None:
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
                return f"Removed {target}, which had just been created."
            source = Path(backup)
            if not source.exists():
                raise JournalError(f"the backup '{source}' is gone")
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            return f"Restored the previous contents of {target}."

        if op == "move":
            source = Path(entry["source"])
            destination = Path(entry["destination"])
            if not destination.exists():
                raise JournalError(f"'{destination}' no longer exists")
            if source.exists():
                raise JournalError(f"'{source}' exists again; remove it first")
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(source))
            return f"Moved {destination} back to {source}."

        raise JournalError(f"unknown operation '{op}'")

    # ------------------------------------------------------------------
    def history(self, limit: int = 10) -> str:
        """Human-readable summary of the most recent actions, newest first."""

        records = self.entries()[-limit:]
        if not records:
            return "No recorded changes yet."
        lines = []
        for record in reversed(records):
            op = record.get("op", "?")
            when = record.get("ts", "?")
            if op == "move":
                what = f"{record.get('source')} -> {record.get('destination')}"
            else:
                what = str(record.get("path"))
            lines.append(f"{when}  {op:<7} {what}")
        return "Recent changes (newest first):\n" + "\n".join(lines)
