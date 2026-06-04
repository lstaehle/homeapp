from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot import (
    CONFIRM,
    DATE,
    DESCRIPTION,
    DURATION,
    TIME_STATE,
    TITLE,
    cmd_cancel,
    cmd_neuesevent,
    cmd_skip_description,
    receive_confirm,
    receive_date,
    receive_duration,
    receive_time,
    receive_title,
)
from telegram.ext import ConversationHandler


def _update(text: str):
    u = MagicMock()
    u.message.text = text
    u.message.reply_text = AsyncMock()
    return u


def _context(user_data=None):
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    return ctx


async def test_neuesevent_happy_path():
    ctx = _context()

    assert await cmd_neuesevent(_update(""), ctx) == TITLE
    assert await receive_title(_update("Kindergeburtstag"), ctx) == DATE
    assert ctx.user_data["title"] == "Kindergeburtstag"
    assert await receive_date(_update("25.12.2026"), ctx) == TIME_STATE
    assert await receive_time(_update("14:00"), ctx) == DURATION
    assert await receive_duration(_update("2h"), ctx) == DESCRIPTION

    with patch("app.bot.create_event") as mock_create:
        assert await cmd_skip_description(_update(""), ctx) == CONFIRM
        confirm_update = _update("Ja")
        result = await receive_confirm(confirm_update, ctx)

    assert result == ConversationHandler.END
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["title"] == "Kindergeburtstag"


async def test_neuesevent_cancel_mid_flow():
    ctx = _context()

    await cmd_neuesevent(_update(""), ctx)
    await receive_title(_update("Test"), ctx)
    await receive_date(_update("01.01.2027"), ctx)

    with patch("app.bot.create_event") as mock_create:
        cancel_update = _update("/abbrechen")
        result = await cmd_cancel(cancel_update, ctx)

    assert result == ConversationHandler.END
    mock_create.assert_not_called()
    reply = cancel_update.message.reply_text.call_args[0][0]
    assert "Abgebrochen" in reply


async def test_neuesevent_invalid_date_retry():
    ctx = _context()

    await cmd_neuesevent(_update(""), ctx)
    await receive_title(_update("Test Event"), ctx)

    # Invalid date — stays in DATE state
    invalid = _update("not-a-date")
    assert await receive_date(invalid, ctx) == DATE
    invalid.message.reply_text.assert_called()

    # Valid date — advances
    assert await receive_date(_update("15.03.2027"), ctx) == TIME_STATE
    assert ctx.user_data["date"] == date(2027, 3, 15)


async def test_neuesevent_nein_confirmation():
    ctx = _context()

    await cmd_neuesevent(_update(""), ctx)
    await receive_title(_update("Test"), ctx)
    await receive_date(_update("01.06.2027"), ctx)
    await receive_time(_update("10:00"), ctx)
    await receive_duration(_update("1h"), ctx)

    with patch("app.bot.create_event") as mock_create:
        await cmd_skip_description(_update(""), ctx)
        nein_update = _update("Nein")
        result = await receive_confirm(nein_update, ctx)

    assert result == ConversationHandler.END
    mock_create.assert_not_called()
    reply = nein_update.message.reply_text.call_args[0][0]
    assert "Abgebrochen" in reply
