"""Control Jarvis from Telegram.

A long-polling bot with no extra dependency — just the Bot API over HTTPS.
Only user ids listed in ``telegram.allowed_user_ids`` are served; everyone else
is ignored. Because a chat cannot show a confirmation dialog, tools that
require confirmation are refused unless ``allow_confirmations`` is set.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

LOGGER = logging.getLogger(__name__)
API_TEMPLATE = "https://api.telegram.org/bot{token}/{method}"


class TelegramBot:
    """Minimal long-polling Telegram front end."""

    def __init__(self, config, agent_factory: Callable[[Callable[[str, dict], bool]], Any]) -> None:
        self.config = config.telegram
        self.agent_factory = agent_factory
        self.offset = 0
        self._stop = False

    # ------------------------------------------------------------------
    def _call(self, method: str, **payload: Any) -> dict[str, Any]:
        response = requests.post(
            API_TEMPLATE.format(token=self.config.token, method=method),
            json=payload,
            timeout=70,
        )
        response.raise_for_status()
        return response.json()

    def send(self, chat_id: int | str, text: str) -> None:
        text = text or "(empty)"
        for start in range(0, len(text), 3800):
            try:
                self._call("sendMessage", chat_id=chat_id, text=text[start : start + 3800])
            except requests.RequestException as exc:
                LOGGER.warning("Telegram send failed: %s", exc)
                return

    def allowed(self, user_id: int | str) -> bool:
        return str(user_id) in {str(item) for item in self.config.allowed_user_ids}

    # ------------------------------------------------------------------
    def _confirm_hook(self, tool_name: str, arguments: dict) -> bool:
        return bool(self.config.allow_confirmations)

    def handle(self, message: dict[str, Any]) -> None:
        chat_id = (message.get("chat") or {}).get("id")
        user_id = (message.get("from") or {}).get("id")
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return
        if not self.allowed(user_id):
            LOGGER.warning("Ignoring Telegram user %s", user_id)
            return
        if text in {"/start", "/help"}:
            self.send(chat_id, "Jarvis is listening. Send any task in plain language.")
            return

        agent = self.agent_factory(self._confirm_hook)
        try:
            reply = agent.run(text)
        except Exception as exc:  # noqa: BLE001 - report the failure to the chat
            reply = f"Error: {exc}"
        self.send(chat_id, reply)

    # ------------------------------------------------------------------
    def poll_once(self, timeout: int = 30) -> int:
        try:
            data = self._call("getUpdates", offset=self.offset, timeout=timeout)
        except requests.RequestException as exc:
            LOGGER.warning("Telegram polling failed: %s", exc)
            time.sleep(5)
            return 0
        updates = data.get("result") or []
        for update in updates:
            self.offset = int(update.get("update_id", 0)) + 1
            message = update.get("message") or update.get("edited_message")
            if message:
                self.handle(message)
        return len(updates)

    def run(self) -> None:
        if not self.config.token:
            raise ValueError("Set telegram.token (or TELEGRAM_BOT_TOKEN) first.")
        if not self.config.allowed_user_ids:
            raise ValueError(
                "Set telegram.allowed_user_ids — an open bot would give strangers "
                "control of your computer."
            )
        LOGGER.info("Telegram bot started.")
        while not self._stop:
            self.poll_once()

    def stop(self) -> None:
        self._stop = True
