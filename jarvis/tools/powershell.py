"""Run PowerShell scripts - the native way to drive Windows.

``run_shell`` goes through ``cmd.exe`` on Windows, so half of what the OS can
do is out of reach: services, the registry, scheduled tasks, winget queries,
Windows settings and anything returning objects rather than text.

This tool talks to PowerShell directly, with three deliberate choices:

* ``-NoProfile`` - a user's profile cannot slow the call down, print a banner
  or redefine a cmdlet under the assistant's feet;
* ``-EncodedCommand`` - the script travels base64-encoded, so quoting and
  injection simply do not apply;
* the same :class:`~jarvis.security.SecurityPolicy` gate as the shell tool, so
  one kill switch still stops every form of command execution.
"""

from __future__ import annotations

import subprocess

from .. import windows
from ..security import SecurityError, SecurityPolicy
from .base import Tool

_MAX_OUTPUT = 20_000

POWERSHELL_DISABLED_MESSAGE = (
    "PowerShell execution is disabled (set JARVIS_ALLOW_SHELL=true to enable)."
)


class PowerShellTool(Tool):
    name = "run_powershell"
    description = (
        "Run a PowerShell script and return its output. On Windows this is the right tool for "
        "services, the registry, scheduled tasks, winget, network and system settings - "
        "run_shell only reaches cmd.exe. Prefer built-in cmdlets over parsing text."
    )
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "script": {"type": "string", "description": "PowerShell script to run."},
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 60).",
                "default": 60,
            },
        },
        "required": ["script"],
    }

    def __init__(self, allow: bool = True, policy: SecurityPolicy | None = None):
        self.policy = policy or SecurityPolicy()
        self.allow = bool(allow) and self.policy.allow_shell

    def run(self, script: str, timeout: int = 60) -> str:
        if not self.allow:
            return POWERSHELL_DISABLED_MESSAGE
        try:
            self.policy.check_command(script)
        except SecurityError as exc:
            return f"Refused: {exc}"
        self.policy.audit("powershell", script)

        try:
            proc = windows.run_powershell(script, timeout=timeout)
        except FileNotFoundError:
            return (
                "PowerShell was not found. It ships with Windows; elsewhere install "
                "PowerShell 7 ('pwsh') or point JARVIS_POWERSHELL at the executable."
            )
        except subprocess.TimeoutExpired:
            return f"PowerShell timed out after {timeout}s."
        except OSError as exc:
            return f"Error running PowerShell: {exc}"

        parts = [f"exit code: {proc.returncode}"]
        if proc.stdout:
            parts.append(f"stdout:\n{proc.stdout.rstrip()[:_MAX_OUTPUT]}")
        if proc.stderr:
            parts.append(f"stderr:\n{proc.stderr.rstrip()[:_MAX_OUTPUT]}")
        return "\n".join(parts)
