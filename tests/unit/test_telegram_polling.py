import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import RetryAfter

from app.main import _poll_telegram


@pytest.mark.parametrize("retry_after", [5, timedelta(seconds=5)])
async def test_polling_honors_telegram_retry_after(retry_after):
    bot_app = MagicMock()
    bot_app.bot.delete_webhook = AsyncMock()
    bot_app.bot.get_updates = AsyncMock(side_effect=[RetryAfter(retry_after), asyncio.CancelledError()])

    with patch("app.main.asyncio.sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(asyncio.CancelledError):
            await _poll_telegram(bot_app)

    sleep.assert_awaited_once_with(6)


async def test_polling_backs_off_and_resets_after_success():
    bot_app = MagicMock()
    bot_app.bot.delete_webhook = AsyncMock()
    bot_app.bot.get_updates = AsyncMock(
        side_effect=[Exception("offline"), Exception("offline"), [], Exception("offline"), asyncio.CancelledError()]
    )

    with patch("app.main.asyncio.sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(asyncio.CancelledError):
            await _poll_telegram(bot_app)

    assert [call.args[0] for call in sleep.await_args_list] == [1, 2, 1]
