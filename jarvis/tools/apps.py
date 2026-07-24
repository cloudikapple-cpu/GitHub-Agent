"""Application and process management.

Installing or removing software is the most dangerous thing the assistant can
do, so it is **disabled by default** and must be switched on explicitly with
``JARVIS_ALLOW_APP_MANAGEMENT=true`` (or ``security.allow_app_management`` in
``config.yaml``). Package managers are auto-detected per platform:

* Windows — ``winget`` (falls back to ``choco``)
* macOS   — ``brew``
* Linux   — ``apt-get`` / ``dnf`` / ``pacman`` (falls back to ``snap``/``flatpak``)
"""

from __future__ import annotations

import platform
import shutil
import subprocess

from ..security import SecurityError, SecurityPolicy
from .base import Tool

_TIMEOUT = 900


def _which(*names: str) -> str | None:
    for name in names:
        if shutil.which(name):
            return name
    return None


def detect_package_manager() -> str | None:
    system = platform.system()
    if system == "Windows":
        return _which("winget", "choco", "scoop")
    if system == "Darwin":
        return _which("brew", "port")
    return _which("apt-get", "dnf", "pacman", "zypper", "snap", "flatpak")


def _command(manager: str, action: str, package: str) -> list[str] | None:
    install = {
        "winget": ["winget", "install", "--silent", "--accept-package-agreements", "--accept-source-agreements", "-e", "--id", package],
        "choco": ["choco", "install", "-y", package],
        "scoop": ["scoop", "install", package],
        "brew": ["brew", "install", package],
        "port": ["sudo", "port", "install", package],
        "apt-get": ["sudo", "apt-get", "install", "-y", package],
        "dnf": ["sudo", "dnf", "install", "-y", package],
        "pacman": ["sudo", "pacman", "-S", "--noconfirm", package],
        "zypper": ["sudo", "zypper", "--non-interactive", "install", package],
        "snap": ["sudo", "snap", "install", package],
        "flatpak": ["flatpak", "install", "-y", package],
    }
    uninstall = {
        "winget": ["winget", "uninstall", "--silent", "-e", "--id", package],
        "choco": ["choco", "uninstall", "-y", package],
        "scoop": ["scoop", "uninstall", package],
        "brew": ["brew", "uninstall", package],
        "port": ["sudo", "port", "uninstall", package],
        "apt-get": ["sudo", "apt-get", "remove", "-y", package],
        "dnf": ["sudo", "dnf", "remove", "-y", package],
        "pacman": ["sudo", "pacman", "-R", "--noconfirm", package],
        "zypper": ["sudo", "zypper", "--non-interactive", "remove", package],
        "snap": ["sudo", "snap", "remove", package],
        "flatpak": ["flatpak", "uninstall", "-y", package],
    }
    table = install if action == "install" else uninstall
    return table.get(manager)


class _AppTool(Tool):
    def __init__(self, policy: SecurityPolicy | None = None):
        self.policy = policy or SecurityPolicy()

    def _run(self, argv: list[str]) -> str:
        self.policy.audit("apps", " ".join(argv))
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=_TIMEOUT)
        except FileNotFoundError:
            return f"Error: '{argv[0]}' is not installed on this system."
        except subprocess.TimeoutExpired:
            return "The package manager timed out."
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
        out = (proc.stdout or "").strip()[:8000]
        err = (proc.stderr or "").strip()[:2000]
        return f"exit code: {proc.returncode}\n{out}\n{err}".strip()


class InstallAppTool(_AppTool):
    name = "install_app"
    description = (
        "Install an application or package with the system package manager "
        "(winget/choco on Windows, brew on macOS, apt/dnf/pacman on Linux)."
    )
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "Package or application id."},
            "manager": {"type": "string", "description": "Force a specific package manager."},
        },
        "required": ["package"],
    }

    def run(self, package: str, manager: str | None = None) -> str:
        try:
            self.policy.check_app_management()
        except SecurityError as exc:
            return f"Refused: {exc}"
        chosen = manager or detect_package_manager()
        if not chosen:
            return "No supported package manager was found on this system."
        argv = _command(chosen, "install", package)
        if not argv:
            return f"Unsupported package manager '{chosen}'."
        return self._run(argv)


class UninstallAppTool(_AppTool):
    name = "uninstall_app"
    description = "Remove an installed application or package. Irreversible — confirm first."
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "Package or application id."},
            "manager": {"type": "string", "description": "Force a specific package manager."},
        },
        "required": ["package"],
    }

    def run(self, package: str, manager: str | None = None) -> str:
        try:
            self.policy.check_app_management()
        except SecurityError as exc:
            return f"Refused: {exc}"
        chosen = manager or detect_package_manager()
        if not chosen:
            return "No supported package manager was found on this system."
        argv = _command(chosen, "uninstall", package)
        if not argv:
            return f"Unsupported package manager '{chosen}'."
        return self._run(argv)


class ListInstalledAppsTool(_AppTool):
    name = "list_installed_apps"
    description = "List installed applications/packages known to the system package manager."
    parameters = {
        "type": "object",
        "properties": {
            "filter": {"type": "string", "description": "Only show entries containing this text."}
        },
    }

    def run(self, filter: str | None = None) -> str:  # noqa: A002 - schema name
        manager = detect_package_manager()
        listings = {
            "winget": ["winget", "list"],
            "choco": ["choco", "list", "--local-only"],
            "scoop": ["scoop", "list"],
            "brew": ["brew", "list"],
            "apt-get": ["apt", "list", "--installed"],
            "dnf": ["dnf", "list", "installed"],
            "pacman": ["pacman", "-Q"],
            "zypper": ["zypper", "se", "-i"],
            "snap": ["snap", "list"],
            "flatpak": ["flatpak", "list"],
        }
        argv = listings.get(manager or "")
        if not argv:
            return "No supported package manager was found on this system."
        output = self._run(argv)
        if filter:
            lines = [line for line in output.splitlines() if filter.lower() in line.lower()]
            return "\n".join(lines[:200]) or f"Nothing matching '{filter}'."
        return "\n".join(output.splitlines()[:200])


class ProcessListTool(_AppTool):
    name = "list_processes"
    description = "List running processes (optionally filtered by name)."
    parameters = {
        "type": "object",
        "properties": {
            "filter": {"type": "string", "description": "Only show processes matching this text."},
            "limit": {"type": "integer", "description": "Max rows (default 40).", "default": 40},
        },
    }

    def run(self, filter: str | None = None, limit: int = 40) -> str:  # noqa: A002
        try:
            import psutil
        except ImportError:
            argv = ["tasklist"] if platform.system() == "Windows" else ["ps", "aux"]
            output = self._run(argv)
            lines = output.splitlines()
            if filter:
                lines = [line for line in lines if filter.lower() in line.lower()]
            return "\n".join(lines[: int(limit)])

        rows = []
        for proc in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]):
            info = proc.info
            name = info.get("name") or ""
            if filter and filter.lower() not in name.lower():
                continue
            rows.append(
                f"{info.get('pid'):>7}  {name[:40]:<40} "
                f"mem {info.get('memory_percent') or 0:.1f}%"
            )
            if len(rows) >= int(limit):
                break
        return "\n".join(rows) or "No matching processes."


class KillProcessTool(_AppTool):
    name = "kill_process"
    description = "Terminate a running process by PID or exact name."
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "pid": {"type": "integer", "description": "Process id to terminate."},
            "name": {"type": "string", "description": "Process name to terminate."},
        },
    }

    def run(self, pid: int | None = None, name: str | None = None) -> str:
        if pid is None and not name:
            return "Provide either a pid or a name."
        self.policy.audit("kill_process", str(pid or name))
        try:
            import psutil
        except ImportError:
            if pid is not None:
                argv = ["taskkill", "/PID", str(pid), "/F"] if platform.system() == "Windows" else ["kill", "-9", str(pid)]
            else:
                argv = ["taskkill", "/IM", str(name), "/F"] if platform.system() == "Windows" else ["pkill", "-f", str(name)]
            return self._run(argv)

        killed = []
        for proc in psutil.process_iter(["pid", "name"]):
            if (pid is not None and proc.info["pid"] == pid) or (
                name and (proc.info.get("name") or "").lower() == name.lower()
            ):
                try:
                    proc.terminate()
                    killed.append(f"{proc.info.get('name')} (pid {proc.info['pid']})")
                except Exception as exc:  # noqa: BLE001
                    return f"Error terminating process: {exc}"
        return "Terminated: " + ", ".join(killed) if killed else "No matching process found."


class SystemInfoTool(_AppTool):
    name = "system_info"
    description = "Report OS, CPU, memory and disk information about this machine."
    parameters = {"type": "object", "properties": {}}

    def run(self) -> str:
        lines = [
            f"system: {platform.system()} {platform.release()}",
            f"machine: {platform.machine()}",
            f"python: {platform.python_version()}",
            f"package manager: {detect_package_manager() or 'not found'}",
        ]
        try:
            import psutil

            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            lines.append(f"cpu cores: {psutil.cpu_count()} (load {psutil.cpu_percent()}%)")
            lines.append(f"memory: {mem.used // 2**20} MiB / {mem.total // 2**20} MiB")
            lines.append(f"disk: {disk.used // 2**30} GiB / {disk.total // 2**30} GiB")
        except Exception:  # noqa: BLE001 - psutil missing or unsupported path
            pass
        return "\n".join(lines)
