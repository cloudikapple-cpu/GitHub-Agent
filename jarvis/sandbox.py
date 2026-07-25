"""Isolated execution for shell commands and generated code.

With ``execution_sandbox.mode`` set to ``docker`` or ``firejail`` the assistant
still has full power inside a box, but a mistake cannot touch the rest of the
machine. ``none`` (default) runs directly on the host.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    mode: str = "none"

    def format(self, limit: int = 4000) -> str:
        parts = [f"exit code: {self.exit_code} (sandbox: {self.mode})"]
        if self.stdout.strip():
            parts.append(f"stdout:\n{self.stdout.strip()[:limit]}")
        if self.stderr.strip():
            parts.append(f"stderr:\n{self.stderr.strip()[:limit]}")
        return "\n\n".join(parts)


class SandboxUnavailable(RuntimeError):
    """Raised when the requested isolation tool is not installed."""


class Sandbox:
    """Build and run commands inside the configured isolation layer."""

    def __init__(self, config=None) -> None:
        from .config import SandboxConfig

        self.config = config or SandboxConfig()

    # ------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return (self.config.mode or "none").lower()

    @property
    def enabled(self) -> bool:
        return self.mode in {"docker", "firejail"}

    def available(self) -> bool:
        if self.mode == "docker":
            return shutil.which("docker") is not None
        if self.mode == "firejail":
            return shutil.which("firejail") is not None
        return True

    def workdir(self) -> Path:
        path = Path(self.config.workdir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    def wrap(self, command: str, cwd: str | None = None) -> list[str] | str:
        """Return the argv (or shell string) that executes ``command`` safely."""

        if self.mode == "docker":
            if shutil.which("docker") is None:
                raise SandboxUnavailable("docker is not installed or not on PATH.")
            mount = str(Path(cwd).expanduser() if cwd else self.workdir())
            argv = [
                "docker", "run", "--rm", "-i",
                "--memory", str(self.config.memory_limit),
                "--pids-limit", "256",
                "-v", f"{mount}:/work",
                "-w", "/work",
            ]
            if not self.config.network:
                argv += ["--network", "none"]
            argv += [self.config.image, "sh", "-lc", command]
            return argv

        if self.mode == "firejail":
            if shutil.which("firejail") is None:
                raise SandboxUnavailable("firejail is not installed or not on PATH.")
            argv = ["firejail", "--quiet", "--private-tmp", "--noroot"]
            if not self.config.network:
                argv.append("--net=none")
            argv += ["sh", "-lc", command]
            return argv

        return command

    # ------------------------------------------------------------------
    def run(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> SandboxResult:
        """Execute ``command`` and capture its output."""

        wrapped = self.wrap(command, cwd=cwd)
        limit = timeout or self.config.timeout
        working_dir = str(Path(cwd).expanduser()) if cwd else None

        try:
            completed = subprocess.run(
                wrapped,
                shell=isinstance(wrapped, str),
                cwd=working_dir if not self.enabled else None,
                capture_output=True,
                text=True,
                timeout=limit,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(124, "", f"Timed out after {limit}s.", self.mode)

        return SandboxResult(
            completed.returncode, completed.stdout or "", completed.stderr or "", self.mode
        )
