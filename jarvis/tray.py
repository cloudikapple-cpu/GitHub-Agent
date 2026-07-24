"""System tray icon for the background daemon.

Gives the daemon a visible home: open the window, start voice capture, or quit
— without touching the terminal. Requires the optional ``pystray`` extra; when
it is missing the daemon simply runs without an icon.
"""

from __future__ import annotations

import logging
from typing import Callable

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    import pystray
    from PIL import Image, ImageDraw

    TRAY_AVAILABLE = True
except ImportError:  # pragma: no cover
    pystray = None  # type: ignore[assignment]
    TRAY_AVAILABLE = False


def _icon_image(size: int = 64):
    """Draw a simple blue circle with a white core."""

    image = Image.new("RGB", (size, size), (18, 22, 30))
    draw = ImageDraw.Draw(image)
    draw.ellipse((6, 6, size - 6, size - 6), fill=(56, 132, 255))
    draw.ellipse((size // 3, size // 3, size - size // 3, size - size // 3), fill=(255, 255, 255))
    return image


class TrayIcon:
    """Thin wrapper around :mod:`pystray`."""

    def __init__(
        self,
        on_open: Callable[[], None],
        on_voice: Callable[[], None],
        on_quit: Callable[[], None],
        hotkey: str = "",
    ) -> None:
        self.on_open = on_open
        self.on_voice = on_voice
        self.on_quit = on_quit
        self.hotkey = hotkey
        self._icon = None

    def available(self) -> bool:
        return TRAY_AVAILABLE

    def start(self) -> bool:
        """Show the icon in a background thread. Returns False when unavailable."""

        if not TRAY_AVAILABLE:
            LOGGER.info("Tray icon unavailable (pip install 'jarvis-desktop[tray]').")
            return False

        title = f"Jarvis ({self.hotkey})" if self.hotkey else "Jarvis"
        menu = pystray.Menu(
            pystray.MenuItem("Ask Jarvis", lambda: self.on_open(), default=True),
            pystray.MenuItem("Voice command", lambda: self.on_voice()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self.stop()),
        )
        self._icon = pystray.Icon("jarvis", _icon_image(), title, menu)
        self._icon.run_detached()
        return True

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.visible = False
            self._icon.stop()
            self._icon = None
        self.on_quit()
