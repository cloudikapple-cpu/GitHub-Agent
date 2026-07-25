"""Windows 11 integration helpers.

This module is import-safe everywhere: every entry point checks the platform
and degrades to ``False`` or ``None`` on Linux and macOS, so the rest of Jarvis
never has to branch on ``sys.platform``.

What lives here:

* :func:`run_powershell` - runs a script through ``-EncodedCommand``. Base64 of
  UTF-16LE removes every quoting and injection problem, and ``-NoProfile``
  means a user's profile cannot slow the call down or change its behaviour.
* :func:`toast` - a real Windows 11 toast with optional buttons, replacing the
  tray balloon that Windows 10 deprecated years ago.
* :func:`schtasks` and :func:`task_xml` - Task Scheduler access, used by the
  autostart module. A logon task survives 'disable' clicks in Task Manager,
  can be delayed until the desktop is ready and restarts after a crash.
* :func:`hotkey_available` - asks the OS whether a shortcut is already taken,
  so the daemon can say so instead of silently doing nothing.
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

IS_WINDOWS = sys.platform.startswith("win")

TASK_NAME = "Jarvis"
DEFAULT_TIMEOUT = 30
# Windows only shows a toast for a registered application id. PowerShell's own
# id is always present, so it is the safest default for a pip-installed app.
DEFAULT_AUMID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
# subprocess.CREATE_NO_WINDOW - spelled out so this module imports on POSIX.
CREATE_NO_WINDOW = 0x08000000

MODIFIERS = {
    "alt": 0x0001,
    "option": 0x0001,
    "ctrl": 0x0002,
    "control": 0x0002,
    "shift": 0x0004,
    "win": 0x0008,
    "cmd": 0x0008,
    "super": 0x0008,
}

VIRTUAL_KEYS = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
}
VIRTUAL_KEYS.update({f"f{n}": 0x6F + n for n in range(1, 25)})

__all__ = [
    "CREATE_NO_WINDOW",
    "DEFAULT_AUMID",
    "IS_WINDOWS",
    "TASK_NAME",
    "encode_command",
    "hotkey_available",
    "no_window_kwargs",
    "parse_combo",
    "powershell_argv",
    "powershell_executable",
    "pythonw_executable",
    "run_powershell",
    "schtasks",
    "task_xml",
    "toast",
    "toast_script",
    "toast_xml",
]


# ---------------------------------------------------------------- processes
def no_window_kwargs() -> dict[str, int]:
    """Keyword arguments that stop a console window from flashing."""

    return {"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}


def powershell_executable() -> str:
    """The interpreter to use: Windows PowerShell, or pwsh elsewhere."""

    override = os.getenv("JARVIS_POWERSHELL", "").strip()
    if override:
        return override
    return "powershell" if IS_WINDOWS else "pwsh"


def encode_command(script: str) -> str:
    """Encode a script the way ``-EncodedCommand`` expects it."""

    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def powershell_argv(script: str) -> list[str]:
    """Build the full argument list for a non-interactive PowerShell call."""

    return [
        powershell_executable(),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encode_command(script),
    ]


def run_powershell(script: str, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run a PowerShell script and capture its output.

    The script is passed base64-encoded, so quotes, newlines and non-ASCII text
    survive intact and no shell parsing happens on the way.
    """

    return subprocess.run(
        powershell_argv(script),
        capture_output=True,
        text=True,
        timeout=timeout,
        **no_window_kwargs(),
    )


def pythonw_executable() -> str:
    """The console-less interpreter, so autostart does not flash a black box."""

    executable = Path(sys.executable or "python")
    if IS_WINDOWS and executable.name.lower() == "python.exe":
        candidate = executable.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return str(executable)


# ------------------------------------------------------------------- toasts
def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def toast_xml(
    title: str,
    message: str,
    actions: list[tuple[str, str]] | None = None,
) -> str:
    """Build the toast payload.

    ``actions`` is a list of ``(label, uri)`` pairs rendered as buttons. The URI
    is opened by the shell when the button is pressed, so a reminder can offer
    'Open the folder' or 'Open the document' without a running listener.
    """

    buttons = "".join(
        f'<action content="{_escape(label)}" arguments="{_escape(uri)}" activationType="protocol"/>'
        for label, uri in (actions or [])
        if label and uri
    )
    actions_block = f"<actions>{buttons}</actions>" if buttons else ""
    return (
        '<toast activationType="protocol">'
        '<visual><binding template="ToastGeneric">'
        f"<text>{_escape(title)}</text>"
        f"<text>{_escape(message)}</text>"
        "</binding></visual>"
        f"{actions_block}"
        "</toast>"
    )


def toast_script(
    title: str,
    message: str,
    actions: list[tuple[str, str]] | None = None,
    app_id: str = "",
) -> str:
    """PowerShell that shows the toast, with every string base64-encoded."""

    payload = base64.b64encode(toast_xml(title, message, actions).encode("utf-8")).decode("ascii")
    aumid = app_id or os.getenv("JARVIS_TOAST_APP_ID", "").strip() or DEFAULT_AUMID
    aumid_payload = base64.b64encode(aumid.encode("utf-8")).decode("ascii")
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
        " ContentType = WindowsRuntime] | Out-Null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom,"
        " ContentType = WindowsRuntime] | Out-Null\n"
        f"$payload = [System.Convert]::FromBase64String('{payload}')\n"
        f"$appIdBytes = [System.Convert]::FromBase64String('{aumid_payload}')\n"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        "$xml.LoadXml([System.Text.Encoding]::UTF8.GetString($payload))\n"
        "$notification = New-Object Windows.UI.Notifications.ToastNotification $xml\n"
        "$appId = [System.Text.Encoding]::UTF8.GetString($appIdBytes)\n"
        "[Windows.UI.Notifications.ToastNotificationManager]"
        "::CreateToastNotifier($appId).Show($notification)\n"
    )


def toast(
    title: str,
    message: str,
    actions: list[tuple[str, str]] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> bool:
    """Show a Windows toast. Returns False when it could not be shown."""

    if not IS_WINDOWS:
        return False
    try:
        proc = run_powershell(toast_script(title, message, actions), timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        LOGGER.debug("Toast failed: %s", exc)
        return False
    if proc.returncode != 0:
        LOGGER.debug("Toast failed: %s", (proc.stderr or "").strip())
        return False
    return True


# ----------------------------------------------------------- task scheduler
def schtasks(*args: str, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Call ``schtasks.exe`` and capture its output."""

    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        **no_window_kwargs(),
    )


def task_xml(command: str, arguments: str = "", delay: str = "PT30S") -> str:
    """Task Scheduler definition for a logon task.

    The delay lets Explorer finish starting before Jarvis grabs its hotkey, and
    ``RestartOnFailure`` brings the daemon back if it dies.
    """

    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        "    <Author>Jarvis</Author>\n"
        "    <Description>Start the Jarvis assistant daemon at logon.</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        f"    <LogonTrigger><Enabled>true</Enabled><Delay>{_escape(delay)}</Delay></LogonTrigger>\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        "      <LogonType>InteractiveToken</LogonType>\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
        "    <IdleSettings>\n"
        "      <StopOnIdleEnd>false</StopOnIdleEnd>\n"
        "      <RestartOnIdle>false</RestartOnIdle>\n"
        "    </IdleSettings>\n"
        "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
        "    <Enabled>true</Enabled>\n"
        "    <Hidden>false</Hidden>\n"
        "    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n"
        "    <WakeToRun>false</WakeToRun>\n"
        "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
        "    <Priority>7</Priority>\n"
        "    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{_escape(command)}</Command>\n"
        f"      <Arguments>{_escape(arguments)}</Arguments>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


# ----------------------------------------------------------------- hotkeys
def parse_combo(combo: str) -> tuple[int, int] | None:
    """Translate ``ctrl+alt+space`` into ``(modifier mask, virtual key)``.

    Returns ``None`` when the combination cannot be expressed that way, for
    example when it has no non-modifier key or uses an unknown name.
    """

    modifiers = 0
    key: int | None = None
    for raw in combo.lower().replace(" ", "").split("+"):
        if not raw:
            continue
        if raw in MODIFIERS:
            modifiers |= MODIFIERS[raw]
        elif raw in VIRTUAL_KEYS:
            key = VIRTUAL_KEYS[raw]
        elif len(raw) == 1 and (raw.isalpha() or raw.isdigit()):
            key = ord(raw.upper())
        else:
            return None
    if key is None:
        return None
    return modifiers, key


def hotkey_available(combo: str) -> bool | None:
    """Is this shortcut free?

    ``True`` when Windows granted it, ``False`` when another application holds
    it, ``None`` when the answer is unknown (not Windows, or an unparseable
    combination). The probe registers the hotkey and immediately releases it.
    """

    if not IS_WINDOWS:
        return None
    parsed = parse_combo(combo)
    if parsed is None:
        return None
    modifiers, key = parsed
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - no user32 means no answer
        return None

    probe_id = 0xB0B0
    mod_norepeat = 0x4000
    try:
        granted = bool(user32.RegisterHotKey(None, probe_id, modifiers | mod_norepeat, key))
        if granted:
            user32.UnregisterHotKey(None, probe_id)
    except Exception:  # noqa: BLE001 - a failed probe must never break startup
        return None
    return granted
