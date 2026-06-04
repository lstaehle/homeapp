import os
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID_1", "123456")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_2", "")


async def test_job_exception_sends_telegram():
    bot = AsyncMock()

    with patch("app.reminders.get_events_today", side_effect=Exception("calendar down")):
        from app.reminders import daily_reminder
        await daily_reminder(bot)

    bot.send_message.assert_called_once()
    text = bot.send_message.call_args.kwargs["text"]
    assert "⚠️ Homeapp Fehler" in text


async def test_error_message_contains_job_name():
    bot = AsyncMock()

    with patch("app.reminders.get_events_today", side_effect=Exception("timeout")):
        from app.reminders import daily_reminder
        await daily_reminder(bot)

    text = bot.send_message.call_args.kwargs["text"]
    assert "daily_reminder" in text
