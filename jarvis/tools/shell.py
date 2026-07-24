"""Run shell commands and Python snippets on the local machine.

Both tools are gated twice:

1. the :class:`~jarvis.security.SecurityPolicy` (kill switch + deny-list), and
2. interactive confirmation (``requires_confirmation``).

``JARVIS_ALLOW_SHELL=false`` disables the shell, ``JARVIS_ALLOW_EXEC=false``
disables Python execution as well — the two are separate on purpose, since
running Python is just as powerful as running a shell.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ..security import SecurityError, SecurityPolicy
from .base import Tool

_MAX_OUTPUT = 20_000


def _format(proc: subprocess.CompletedProcess[str]) -> str:
    parts = [f"exit code: {proc.returncode}"]
    if proc.stdout:
        parts.append(f"stdout:\n{proc.stdout.rstrip()[:_MAX_OUTPUT]}")
    if proc.stderr:
        parts.append(f"stderr:\n{proc.stderr.rstrip()[:_MAX_OUTPUT]}")
    return "\n".join(parts)


class ShellTool(Tool):
    name = "run_shell"
    description = (
        "Run a shell command on the local machine and return its stdout/stderr. "
        "Use for launching programs, file operations, git, package managers, etc."
    )
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run."},
            "cwd": {"type": "string", "description": "Working directory for the command."},
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 60).",
                "default": 60,
            },
        },
        "required": ["command"],
    }

    def __init__(self, allow: bool = True, policy: SecurityPolicy | None = None):
        self.policy = policy or SecurityPolicy()
        # An explicit allow=False always wins, for direct/programmatic use.
        if not allow:
            self.policy.allow_shell = False
        self.allow = self.policy.allow_shell

    def run(self, command: str, cwd: str | None = None, timeout: int = 60) -> str:
        try:
            self.policy.check_command(command)
            workdir = str(self.policy.check_path(cwd)) if cwd else None
        except SecurityError as exc:
            return f"Refused: {exc}"
        if workdir and not Path(workdir).is_dir():
            return f"Error: working directory '{cwd}' does not exist."
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workdir,
            )
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s."
        except Exception as exc:  # noqa: BLE001
            return f"Error running command: {exc}"
        return _format(proc)


class PythonExecTool(Tool):
    name = "run_python"
    description = (
        "Execute a snippet of Python code in a subprocess and return its output. "
        "Useful for calculations, data processing, or quick scripting."
    )
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python source code to execute."},
            "cwd": {"type": "string", "description": "Working directory for the process."},
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 60).",
                "default": 60,
            },
        },
        "required": ["code"],
    }

    def __init__(self, policy: SecurityPolicy | None = None):
        self.policy = policy or SecurityPolicy()

    def run(self, code: str, cwd: str | None = None, timeout: int = 60) -> str:
        try:
            self.policy.check_exec()
            workdir = str(self.policy.check_path(cwd)) if cwd else None
        except SecurityError as exc:
            return f"Refused: {exc}"
        self.policy.audit("python", code)
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workdir,
            )
        except subprocess.TimeoutExpired:
            return f"Code timed out after {timeout}s."
        except Exception as exc:  # noqa: BLE001
            return f"Error executing code: {exc}"
        return _format(proc)
