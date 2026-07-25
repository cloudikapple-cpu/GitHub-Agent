"""Telegram front end: access control, context and validation."""

from __future__ import annotations

import pytest

from jarvis.config import Config, TelegramConfig
from jarvis.telegram_bot import TelegramBot


class FakeAgent:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def run(self, text: str) -> str:
        self.seen.append(text)
        return f"done: {text}"


def build(**kwargs):
    config = Config()
    config.telegram = TelegramConfig(
        enabled=True, token="token", allowed_user_ids=[42], **kwargs
    )
    agents: list[FakeAgent] = []

    def factory(_confirm_hook):
        agent = FakeAgent()
        agents.append(agent)
        return agent

    bot = TelegramBot(config, factory)
    bot.sent = []  # type: ignore[attr-defined]
    bot.send = lambda chat_id, text: bot.sent.append((chat_id, text))  # type: ignore[assignment]
    return bot, agents


def message(text: str, user_id: int = 42, chat_id: int = 7) -> dict:
    return {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": text}


def test_strangers_are_ignored():
    bot, agents = build()
    bot.handle(message("delete everything", user_id=999))
    assert agents == [] and bot.sent == []


def test_allowed_user_gets_an_answer():
    bot, agents = build()
    bot.handle(message("hello"))
    assert bot.sent == [(7, "done: hello")]
    assert agents[0].seen == ["hello"]


def test_each_chat_keeps_its_own_agent_and_context():
    bot, agents = build()
    bot.handle(message("first", chat_id=1))
    bot.handle(message("second", chat_id=1))
    bot.handle(message("other", chat_id=2))
    assert len(agents) == 2
    assert agents[0].seen == ["first", "second"]


def test_reset_drops_the_conversation():
    bot, agents = build()
    bot.handle(message("first"))
    bot.handle(message("/reset"))
    bot.handle(message("second"))
    assert len(agents) == 2


def test_a_failing_run_is_reported_not_raised():
    bot, _ = build()

    class Boom:
        def run(self, _text):
            raise RuntimeError("model offline")

    bot._agents[7] = Boom()
    bot.handle(message("hi"))
    assert "model offline" in bot.sent[0][1]


def test_confirmations_are_refused_by_default():
    bot, _ = build()
    assert bot._confirm_hook("delete_path", {}) is False
    permissive, _ = build(allow_confirmations=True)
    assert permissive._confirm_hook("delete_path", {}) is True


def test_a_bot_without_a_whitelist_refuses_to_start():
    config = Config()
    config.telegram = TelegramConfig(enabled=True, token="token", allowed_user_ids=[])
    with pytest.raises(ValueError):
        TelegramBot(config, lambda _hook: FakeAgent()).validate()


def test_a_bot_without_a_token_refuses_to_start():
    config = Config()
    config.telegram = TelegramConfig(enabled=True, token="", allowed_user_ids=[42])
    with pytest.raises(ValueError):
        TelegramBot(config, lambda _hook: FakeAgent()).validate()
