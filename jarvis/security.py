"""Security layer: path sandboxing, command filtering and an audit log.

The assistant can touch the real machine, so every filesystem and execution
tool routes through a :class:`SecurityPolicy`. The policy is intentionally
permissive by default (so the tool set keeps working out of the box) but every
dangerous default can be tightened in ``config.yaml`` / ``.env``.

Design:

* ``allowed_roots`` — if non-empty, paths must live under one of these roots.
* ``denied_path_patterns`` — glob patterns that are always refused (secrets).
* ``denied_command_patterns`` — regexes matched against shell commands.
* ``audit`` — append-only JSONL log of every guarded action.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

#: Files that should never be read or written by the assistant.
DEFAULT_DENIED_PATH_PATTERNS: list[str] = [
    "*/.ssh/*",
    "*/.gnupg/*",
    "*/.aws/*",
    "*/.config/gcloud/*",
    "*/.env",
    "*.pem",
    "*id_rsa*",
    "*id_ed25519*",
    "*/.git-credentials",
    "*/shadow",
]

#: Commands that are refused outright, even with confirmation enabled.
DEFAULT_DENIED_COMMAND_PATTERNS: list[str] = [
    r"rm\s+(-[a-zA-Z]*\s+)*-?[rf]{1,2}\s+/(\s|$)",
    r":\(\)\s*\{.*\};\s*:",
    r"\bmkfs(\.|\s)",
    r"\bdd\b[^\n]*of=/dev/",
    r"chmod\s+-R\s+777\s+/(\s|$)",
    r"\b(shutdown|halt|poweroff)\b",
    r">\s*/dev/sd[a-z]",
    r"(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|k)?sh",
    r"Remove-Item\s+-Recurse\s+-Force\s+[A-Za-z]:\\\\?(\s|$)",
    r"Format-Volume",
    r"\bdiskpart\b",
]


class SecurityError(Exception):
    """Raised when an action is refused by the policy."""


@dataclass
class SecurityPolicy:
    """Runtime guard rails for filesystem, shell and app management tools."""

    allowed_roots: list[str] = field(default_factory=list)
    denied_path_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_DENIED_PATH_PATTERNS)
    )
    denied_command_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_DENIED_COMMAND_PATTERNS)
    )
    allow_shell: bool = True
    allow_exec: bool = True
    allow_desktop: bool = True
    allow_app_management: bool = False
    allow_network: bool = True
    audit_log: str = ""

    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        self._roots = [Path(r).expanduser().resolve() for r in self.allowed_roots if r]
        self._denied_commands = [
            re.compile(p, re.IGNORECASE) for p in self.denied_command_patterns
        ]

    # ------------------------------------------------------------------
    def check_path(self, path: str | os.PathLike[str], write: bool = False) -> Path:
        """Resolve ``path`` and raise :class:`SecurityError` if it is off limits."""

        resolved = Path(path).expanduser()
        try:
            resolved = resolved.resolve()
        except OSError:  # pragma: no cover - broken symlink etc.
            resolved = resolved.absolute()

        as_posix = resolved.as_posix()
        for pattern in self.denied_path_patterns:
            if fnmatch.fnmatch(as_posix, pattern) or fnmatch.fnmatch(resolved.name, pattern):
                raise SecurityError(
                    f"Path '{resolved}' is blocked by policy (pattern '{pattern}')."
                )

        if self._roots and not any(
            resolved == root or root in resolved.parents for root in self._roots
        ):
            allowed = ", ".join(str(r) for r in self._roots)
            raise SecurityError(
                f"Path '{resolved}' is outside the allowed workspace ({allowed})."
            )

        self.audit("path_write" if write else "path_read", str(resolved))
        return resolved

    # ------------------------------------------------------------------
    def check_command(self, command: str) -> str:
        """Validate a shell command against the deny list."""

        if not self.allow_shell:
            raise SecurityError(
                "Shell execution is disabled (set JARVIS_ALLOW_SHELL=true to enable)."
            )
        for pattern in self._denied_commands:
            if pattern.search(command):
                raise SecurityError(
                    f"Command refused by policy (matched '{pattern.pattern}')."
                )
        self.audit("shell", command)
        return command

    def check_exec(self) -> None:
        if not self.allow_exec:
            raise SecurityError(
                "Code execution is disabled (set JARVIS_ALLOW_EXEC=true to enable)."
            )

    def check_desktop(self) -> None:
        if not self.allow_desktop:
            raise SecurityError(
                "Desktop control is disabled (set JARVIS_ALLOW_DESKTOP=true to enable)."
            )

    def check_app_management(self) -> None:
        if not self.allow_app_management:
            raise SecurityError(
                "Installing/removing applications is disabled "
                "(set JARVIS_ALLOW_APP_MANAGEMENT=true to enable)."
            )

    def check_network(self) -> None:
        if not self.allow_network:
            raise SecurityError("Network access is disabled by policy.")

    # ------------------------------------------------------------------
    def audit(self, kind: str, detail: str) -> None:
        """Append a line to the audit log (best effort, never raises)."""

        if not self.audit_log:
            return
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "kind": kind,
            "detail": detail[:2000],
        }
        try:
            path = Path(self.audit_log).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:  # pragma: no cover - logging must never break a run
            pass


#: A permissive policy used when a tool is constructed without one.
def default_policy() -> SecurityPolicy:
    return SecurityPolicy()
