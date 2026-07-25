"""Cross-platform desktop notifications (best effort, never raises).

On Windows 11 a real toast is shown through the WinRT notification manager, so
it lands in the Notification Centre and can carry buttons. The old tray balloon
is kept only as a fallback - it is deprecated, it disappears after a few
seconds and it cannot be recovered once missed.

Every string is passed to PowerShell base64-encoded, so an apostrophe in a
reminder can neither break the command nor inject anything into it.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess

from . import windows

LOGGER = logging.getLogger(__name__)


def _balloon(title: str, message: str) -> bool:
    """Deprecated Windows Forms balloon, used when WinRT is unavailable."""

    script = (
        "[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null;"
        "$n = New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon = [System.Drawing.SystemIcons]::Information;"
        "$n.Visible = $true;"
        "$n.ShowBalloonTip(8000, $env:JARVIS_TOAST_TITLE, $env:JARVIS_TOAST_BODY,"
        "[System.Windows.Forms.ToolTipIcon]::Info);"
        "Start-Sleep -Seconds 8"
    )
    import os

    env = dict(os.environ, JARVIS_TOAST_TITLE=title, JARVIS_TOAST_BODY=message)
    try:
        proc = subprocess.run(
            windows.powershell_argv(script),
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            **windows.no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        LOGGER.debug("Balloon failed: %s", exc)
        return False
    return proc.returncode == 0


def notify(
    title: str,
    message: str,
    actions: list[tuple[str, str]] | None = None,
) -> str:
    """Show a desktop notification. Returns a human-readable status string.

    ``actions`` is a list of ``(label, uri)`` pairs shown as toast buttons on
    Windows and ignored elsewhere - a reminder can offer 'Open the folder'
    without the daemon having to stay in the loop.
    """

    system = platform.system()

    if system == "Windows":
        if windows.toast(title, message, actions):
            return "Notification shown."
        if _balloon(title, message):
            return "Notification shown (balloon fallback)."
        return f"{title}: {message}"

    try:
        from plyer import notification as plyer_notification  # type: ignore

        plyer_notification.notify(title=title, message=message, app_name="Jarvis", timeout=8)
        return "Notification shown."
    except Exception:  # noqa: BLE001 - fall through to platform tools
        pass

    try:
        if system == "Darwin":
            script = f"display notification {message!r} with title {title!r}"
            subprocess.run(["osascript", "-e", script], check=False, timeout=10)
            return "Notification shown."
        if system == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], check=False, timeout=10)
            return "Notification shown."
    except Exception as exc:  # noqa: BLE001
        return f"Could not show notification: {exc}"

    return f"{title}: {message}"
