"""Cross-platform desktop notifications (best effort, never raises)."""

from __future__ import annotations

import platform
import shutil
import subprocess


def notify(title: str, message: str) -> str:
    """Show a desktop notification. Returns a human-readable status string."""

    try:
        from plyer import notification as plyer_notification  # type: ignore

        plyer_notification.notify(title=title, message=message, app_name="Jarvis", timeout=8)
        return "Notification shown."
    except Exception:  # noqa: BLE001 - fall through to platform tools
        pass

    system = platform.system()
    try:
        if system == "Darwin":
            script = f'display notification {message!r} with title {title!r}'
            subprocess.run(["osascript", "-e", script], check=False, timeout=10)
            return "Notification shown."
        if system == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], check=False, timeout=10)
            return "Notification shown."
        if system == "Windows":
            ps = (
                "[reflection.assembly]::loadwithpartialname('System.Windows.Forms');"
                "$n=New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
                f"$n.ShowBalloonTip(8000,'{title}','{message}',"
                "[System.Windows.Forms.ToolTipIcon]::Info)"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False, timeout=15)
            return "Notification shown."
    except Exception as exc:  # noqa: BLE001
        return f"Could not show notification: {exc}"

    return f"{title}: {message}"
