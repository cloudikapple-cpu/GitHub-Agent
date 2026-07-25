"""Single-instance lock for the daemon.

Two daemons mean two schedulers, duplicated reminders and a fight over the
global hotkey. :class:`SingleInstance` writes a PID file and refuses to start
when the process it names is still alive; stale files left by a crash or a
reboot are reclaimed automatically.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from types import TracebackType

LOGGER = logging.getLogger(__name__)

DEFAULT_LOCK_PATH = Path.home() / ".jarvis" / "daemon.lock"


class AlreadyRunning(RuntimeError):
    """Raised when another live Jarvis process holds the lock."""

    def __init__(self, pid: int, path: Path):
        super().__init__(f"Jarvis is already running (pid {pid}, lock file {path}).")
        self.pid = pid
        self.path = path


def pid_alive(pid: int) -> bool:
    """Whether a process with this id currently exists."""

    if pid <= 0:
        return False

    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]
    if psutil is not None:
        return bool(psutil.pid_exists(pid))

    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # alive, just owned by somebody else
        return True
    return True


class SingleInstance:
    """PID-file lock usable directly or as a context manager."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path else DEFAULT_LOCK_PATH
        self.acquired = False

    def owner(self) -> int | None:
        """PID of the live process holding the lock, or ``None`` if it is free."""

        try:
            raw = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        try:
            pid = int(raw)
        except ValueError:
            return None
        if not pid_alive(pid):
            LOGGER.debug("Reclaiming the stale lock left by pid %s", pid)
            return None
        return pid

    def acquire(self) -> SingleInstance:
        """Take the lock or raise :class:`AlreadyRunning`."""

        owner = self.owner()
        if owner is not None and owner != os.getpid():
            raise AlreadyRunning(owner, self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(os.getpid()), encoding="utf-8")
        self.acquired = True
        return self

    def release(self) -> None:
        """Release the lock if this process owns it."""

        if not self.acquired:
            return
        try:
            if self.path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                self.path.unlink()
        except OSError:  # pragma: no cover - a missing lock file is fine
            pass
        self.acquired = False

    def __enter__(self) -> SingleInstance:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
