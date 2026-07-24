"""Run shell commands and Python snippets on the local machine.

These tools are powerful. They are gated behind confirmation by default (see
``jarvis.config.Config.require_confirmation``) and shell execution can be turned
off entirely with ``JARVIS_ALLOW_SHELL=false``.
"""

from __future__ import annotations

import subprocess
import sys

from .base import Tool


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
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 60).",
                "default": 60,
            },
        },
        "required": ["command"],
    }

    def __init__(self, allow: bool = True):
        self.allow = allow

    def run(self, command: str, timeout: int = 60) -> str:
        if not self.allow:
            return "Shell execution is disabled (set JARVIS_ALLOW_SHELL=true to enable)."
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s."
        except Exception as exc:  # noqa: BLE001
            return f"Error running command: {exc}"

        parts = [f"exit code: {proc.returncode}"]
        if proc.stdout:
            parts.append(f"stdout:\n{proc.stdout.rstrip()}")
        if proc.stderr:
            parts.append(f"stderr:\n{proc.stderr.rstrip()}")
        return "\n".join(parts)


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
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 60).",
                "default": 60,
            },
        },
        "required": ["code"],
    }

    def run(self, code: str, timeout: int = 60) -> str:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"Code timed out after {timeout}s."
        except Exception as exc:  # noqa: BLE001
            return f"Error executing code: {exc}"

        parts = [f"exit code: {proc.returncode}"]
        if proc.stdout:
            parts.append(f"stdout:\n{proc.stdout.rstrip()}")
        if proc.stderr:
            parts.append(f"stderr:\n{proc.stderr.rstrip()}")
        return "\n".join(parts)
