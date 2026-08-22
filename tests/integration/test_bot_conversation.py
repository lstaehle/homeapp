from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.bot import (
    CONFIRM,
    DATE_TITLE,
    DESCRIPTION,
    DURATION,
    SEX_STYLE,
    TIME_STATE,
    cmd_cancel,
    cmd_love,
    cmd_neuesevent,
    cmd_period,
    cmd_periodhistory,
    cmd_periodnext,
    cmd_sex,
    cmd_skip_description,
    PENDING_SEX_PROPOSALS,
    receive_confirm,
    receive_date_and_title,
    receive_duration,
    receive_natural_confirm,
    receive_sex_confirmation,
    receive_sex_style,
    receive_time,
)
from app.cycle import CycleError
from app.llm_events import ParsedEvent, ParsedSexProposal, LLMEventError
from telegram.ext import ConversationHandler

TZ = ZoneInfo("Europe/Zurich")


def _update(text: str, chat_id: int = 111, first_name: str = "Lorenz"):
    u = MagicMock()
    u.message.text = text
    u.message.reply_text = AsyncMock()
    u.effective_chat.id = chat_id
    u.effective_user.first_name = first_name
    return u


def _context(user_data=None, args=None):
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.args = args if args is not None else []
    ctx.bot.send_message = AsyncMock()
    return ctx


@pytest.fixture
def chat_ids(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID_1", "111")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_2", "222")


async def test_neuesevent_happy_path():
    ctx = _context()

    assert await cmd_neuesevent(_update(""), ctx) == DATE_TITLE
    assert await receive_date_and_title(_update("25.12.2026 Kindergeburtstag"), ctx) == TIME_STATE
    assert ctx.user_data["title"] == "Kindergeburtstag"
    assert ctx.user_data["date"] == date(2026, 12, 25)
    assert await receive_time(_update("14:00"), ctx) == DURATION
    assert await receive_duration(_update("2h"), ctx) == DESCRIPTION

    with patch("app.bot.create_event") as mock_create:
        assert await cmd_skip_description(_update(""), ctx) == CONFIRM
        confirm_update = _update("Ja")
        result = await receive_confirm(confirm_update, ctx)

    assert result == ConversationHandler.END
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["title"] == "Kindergeburtstag"


async def test_inline_event_notifies_other_chat(chat_ids):
    ctx = _context(args=["25.12.2026", "14:00", "Kindergeburtstag"])
    update = _update("/event 25.12.2026 14:00 Kindergeburtstag", chat_id=111, first_name="Lorenz")

    with patch("app.bot.create_event") as mock_create:
        result = await cmd_neuesevent(update, ctx)

    assert result == ConversationHandler.END
    mock_create.assert_called_once()
    ctx.bot.send_message.assert_awaited_once()
    kwargs = ctx.bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 222
    assert "Neuer Termin von Lorenz" in kwargs["text"]
    assert "Kindergeburtstag" in kwargs["text"]
    assert "25.12.2026, 14:00-15:00" in kwargs["text"]


async def test_guided_event_notifies_other_chat_after_confirmation(chat_ids):
    ctx = _context()
    await receive_date_and_title(_update("25.12.2026 Kindergeburtstag"), ctx)
    await receive_time(_update("14:00"), ctx)
    await receive_duration(_update("2h"), ctx)
    await cmd_skip_description(_update(""), ctx)

    with patch("app.bot.create_event"):
        result = await receive_confirm(_update("Ja", chat_id=111, first_name="Lorenz"), ctx)

    assert result == ConversationHandler.END
    kwargs = ctx.bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 222
    assert "Kindergeburtstag" in kwargs["text"]
    assert "25.12.2026, 14:00-16:00" in kwargs["text"]


async def test_natural_event_notifies_reverse_direction(chat_ids):
    event = ParsedEvent(
        title="Zahnarzt",
        start_dt=datetime(2026, 6, 27, 14, 30, tzinfo=TZ),
        end_dt=datetime(2026, 6, 27, 15, 30, tzinfo=TZ),
    )
    ctx = _context(user_data={"nl_event": event})

    with patch("app.bot.create_event"):
        result = await receive_natural_confirm(_update("Ja", chat_id=222, first_name="Anna"), ctx)

    assert result == ConversationHandler.END
    kwargs = ctx.bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 111
    assert "Neuer Termin von Anna" in kwargs["text"]
    assert "Zahnarzt" in kwargs["text"]


async def test_natural_all_day_event_formats_as_all_day(chat_ids):
    event = ParsedEvent(
        title="Schulfrei",
        start_dt=datetime(2026, 7, 1, 0, 0, tzinfo=TZ),
        end_dt=datetime(2026, 7, 1, 0, 0, tzinfo=TZ),
        all_day=True,
    )
    ctx = _context(user_data={"nl_event": event})

    with patch("app.bot.create_event"):
        await receive_natural_confirm(_update("Ja", chat_id=111), ctx)

    assert "01.07.2026, ganztägig" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_no_notification_when_create_event_fails(chat_ids):
    ctx = _context(args=["25.12.2026", "14:00", "Kindergeburtstag"])

    with patch("app.bot.create_event", side_effect=Exception("calendar down")):
        result = await cmd_neuesevent(_update("/event", chat_id=111), ctx)

    assert result == ConversationHandler.END
    ctx.bot.send_message.assert_not_awaited()


async def test_unknown_chat_id_does_not_notify(chat_ids):
    ctx = _context(args=["25.12.2026", "14:00", "Kindergeburtstag"])

    with patch("app.bot.create_event"):
        await cmd_neuesevent(_update("/event", chat_id=999), ctx)

    ctx.bot.send_message.assert_not_awaited()


async def test_neuesevent_cancel_mid_flow():
    ctx = _context()

    await cmd_neuesevent(_update(""), ctx)
    await receive_date_and_title(_update("01.01.2027 Test"), ctx)

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

    invalid = _update("not-a-date")
    assert await receive_date_and_title(invalid, ctx) == DATE_TITLE
    invalid.message.reply_text.assert_called()

    assert await receive_date_and_title(_update("15.03.2027 Test Event"), ctx) == TIME_STATE
    assert ctx.user_data["date"] == date(2027, 3, 15)


async def test_neuesevent_nein_confirmation():
    ctx = _context()

    await receive_date_and_title(_update("01.06.2027 Test"), ctx)
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
    ctx.bot.send_message.assert_not_awaited()


async def test_period_defaults_to_today(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 15, tzinfo=tz)

    monkeypatch.setattr("app.bot.datetime", FixedDateTime)
    ctx = _context(args=[])
    update = _update("/period")

    with patch("app.bot.record_cycle_start") as mock_record:
        await cmd_period(update, ctx)

    mock_record.assert_called_once_with(date(2026, 8, 15))
    assert "15.08.2026" in update.message.reply_text.await_args.args[0]


async def test_period_replies_after_saving_date():
    ctx = _context(args=["15.08.2026"])
    update = _update("/period 15.08.2026")

    with patch("app.bot.record_cycle_start"):
        await cmd_period(update, ctx)

    update.message.reply_text.assert_awaited_once()
    assert "Zyklusstart gespeichert" in update.message.reply_text.await_args.args[0]
    assert "15.08.2026" in update.message.reply_text.await_args.args[0]


async def test_period_invalid_date_does_not_save():
    ctx = _context(args=["invalid"])
    update = _update("/period invalid")

    with patch("app.bot.record_cycle_start") as mock_record:
        await cmd_period(update, ctx)

    mock_record.assert_not_called()
    assert "Ungültiges Datum" in update.message.reply_text.await_args.args[0]


async def test_period_missing_cycle_calendar_id_reports_error():
    ctx = _context(args=["15.08.2026"])
    update = _update("/period 15.08.2026")

    with patch("app.bot.record_cycle_start", side_effect=CycleError("CYCLE_GOOGLE_CALENDAR_ID ist nicht konfiguriert.")):
        await cmd_period(update, ctx)

    assert "CYCLE_GOOGLE_CALENDAR_ID" in update.message.reply_text.await_args.args[0]


async def test_periodhistory_shows_recent_starts_and_average():
    ctx = _context()
    update = _update("/periodhistory")

    with patch("app.bot.get_cycle_starts", return_value=[
        date(2026, 6, 1),
        date(2026, 6, 29),
        date(2026, 7, 28),
    ]):
        await cmd_periodhistory(update, ctx)

    text = update.message.reply_text.await_args.args[0]
    assert "Zyklushistorie" in text
    assert "01.06.2026" in text
    assert "29 Tage" in text
    assert "Durchschnitt: 29 Tage" in text


async def test_periodnext_creates_prediction():
    ctx = _context()
    update = _update("/periodnext")
    prediction = MagicMock()
    prediction.next_start = date(2026, 8, 25)
    prediction.interval_days = 29
    prediction.based_on_cycles = 3

    with (
        patch("app.bot.predict_next_cycle", return_value=prediction),
        patch("app.bot.replace_predicted_cycle_event") as mock_replace,
    ):
        await cmd_periodnext(update, ctx)

    mock_replace.assert_called_once_with(date(2026, 8, 25))
    text = update.message.reply_text.await_args.args[0]
    assert "25.08.2026" in text
    assert "Intervall: 29 Tage" in text
    assert "gespeichert" in text


async def test_love_sends_message_to_other_chat(chat_ids):
    ctx = _context(args=["Ich", "denke", "an", "dich"])
    update = _update('/love Ich denke an dich', chat_id=111, first_name="Lorenz")

    await cmd_love(update, ctx)

    ctx.bot.send_message.assert_awaited_once()
    kwargs = ctx.bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 222
    assert "Liebesnachricht von Lorenz" in kwargs["text"]
    assert "Ich denke an dich" in kwargs["text"]
    assert "Gesendet" in update.message.reply_text.await_args.args[0]


async def test_love_requires_message_text(chat_ids):
    ctx = _context(args=[])
    update = _update('/love', chat_id=111)

    await cmd_love(update, ctx)

    ctx.bot.send_message.assert_not_awaited()
    assert "Bitte einen Text" in update.message.reply_text.await_args.args[0]


async def test_love_unknown_chat_does_not_send(chat_ids):
    ctx = _context(args=["Hallo"])
    update = _update('/love Hallo', chat_id=999)

    await cmd_love(update, ctx)

    ctx.bot.send_message.assert_not_awaited()
    assert "Kein Empfänger" in update.message.reply_text.await_args.args[0]


async def test_sex_with_style_sends_proposal_without_calendar_write(chat_ids):
    PENDING_SEX_PROPOSALS.clear()
    ctx = _context(args=["24.08.2026", "21:30", "romantisch"])
    update = _update("/sex 24.08.2026 21:30 romantisch", chat_id=111)

    with patch("app.bot.schedule_intimacy_event") as mock_schedule:
        result = await cmd_sex(update, ctx)

    assert result == ConversationHandler.END
    mock_schedule.assert_not_called()
    assert PENDING_SEX_PROPOSALS[222]["title"] == "Wir zwei - romantisch"
    assert PENDING_SEX_PROPOSALS[222]["start_dt"].isoformat() == "2026-08-24T21:30:00+02:00"
    send_kwargs = ctx.bot.send_message.await_args.kwargs
    assert send_kwargs["chat_id"] == 222
    assert "Zeit zu zweit vorgeschlagen" in send_kwargs["text"]
    assert "Wir zwei - romantisch" in send_kwargs["text"]
    assert "Antwort: 1 Ja, 2 ein andermal, 3 vielleicht" in send_kwargs["text"]
    assert "Vorschlag gesendet" in update.message.reply_text.await_args.args[0]


async def test_sex_without_style_prompts_for_numbered_style(chat_ids):
    ctx = _context(args=["24.08.2026", "21:30"])
    update = _update("/sex 24.08.2026 21:30", chat_id=111)

    result = await cmd_sex(update, ctx)

    assert result == SEX_STYLE
    assert ctx.user_data["sex_start_dt"].isoformat() == "2026-08-24T21:30:00+02:00"
    prompt = update.message.reply_text.await_args.args[0]
    assert "Welcher Stil?" in prompt
    assert "1 romantisch" in prompt
    assert "5 Überraschung" in prompt


async def test_sex_natural_language_sends_proposal_without_calendar_write(chat_ids):
    PENDING_SEX_PROPOSALS.clear()
    ctx = _context(args=["nächsten", "Mittwoch", "um", "21:00", "-", "frivol"])
    update = _update("/sex nächsten Mittwoch um 21:00 - frivol", chat_id=111)
    proposal = ParsedSexProposal(
        start_dt=datetime(2026, 8, 26, 21, 0, tzinfo=TZ),
        style="schmutzig",
    )

    with (
        patch("app.bot.parse_natural_sex_proposal", return_value=proposal) as mock_parse,
        patch("app.bot.schedule_intimacy_event") as mock_schedule,
    ):
        result = await cmd_sex(update, ctx)

    assert result == ConversationHandler.END
    mock_parse.assert_called_once_with("nächsten Mittwoch um 21:00 - frivol")
    mock_schedule.assert_not_called()
    assert PENDING_SEX_PROPOSALS[222]["title"] == "Wir zwei - schmutzig"
    assert PENDING_SEX_PROPOSALS[222]["start_dt"].isoformat() == "2026-08-26T21:00:00+02:00"
    assert "Wir zwei - schmutzig" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_sex_natural_language_without_style_prompts_for_numbered_style(chat_ids):
    ctx = _context(args=["nächsten", "Mittwoch", "um", "21:00"])
    update = _update("/sex nächsten Mittwoch um 21:00", chat_id=111)
    proposal = ParsedSexProposal(start_dt=datetime(2026, 8, 26, 21, 0, tzinfo=TZ))

    with patch("app.bot.parse_natural_sex_proposal", return_value=proposal):
        result = await cmd_sex(update, ctx)

    assert result == SEX_STYLE
    assert ctx.user_data["sex_start_dt"].isoformat() == "2026-08-26T21:00:00+02:00"
    assert "Welcher Stil?" in update.message.reply_text.await_args.args[0]


async def test_sex_natural_language_parser_error_replies(chat_ids):
    ctx = _context(args=["irgendwann"])
    update = _update("/sex irgendwann", chat_id=111)

    with patch("app.bot.parse_natural_sex_proposal", side_effect=LLMEventError("Kein vollständiger Vorschlag erkannt.")):
        result = await cmd_sex(update, ctx)

    assert result == ConversationHandler.END
    assert "Kein vollständiger Vorschlag" in update.message.reply_text.await_args.args[0]


async def test_sex_style_reply_number_sends_proposal(chat_ids):
    PENDING_SEX_PROPOSALS.clear()
    ctx = _context(user_data={"sex_start_dt": datetime(2026, 8, 24, 21, 30, tzinfo=TZ)})
    update = _update("5", chat_id=111)

    with patch("app.bot.schedule_intimacy_event") as mock_schedule:
        result = await receive_sex_style(update, ctx)

    assert result == ConversationHandler.END
    assert "sex_start_dt" not in ctx.user_data
    mock_schedule.assert_not_called()
    assert PENDING_SEX_PROPOSALS[222]["title"] == "Wir zwei - Überraschung"
    assert "Wir zwei - Überraschung" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_sex_invalid_style_keeps_prompt_state(chat_ids):
    ctx = _context(user_data={"sex_start_dt": datetime(2026, 8, 24, 21, 30, tzinfo=TZ)})
    update = _update("unbekannt", chat_id=111)

    with patch("app.bot.schedule_intimacy_event") as mock_schedule:
        result = await receive_sex_style(update, ctx)

    assert result == SEX_STYLE
    mock_schedule.assert_not_called()
    assert "1, 2, 3, 4 oder 5" in update.message.reply_text.await_args.args[0]


async def test_sex_confirmation_1_saves_calendar_and_notifies_proposer(chat_ids):
    PENDING_SEX_PROPOSALS.clear()
    PENDING_SEX_PROPOSALS[222] = {
        "proposer_chat_id": 111,
        "title": "Wir zwei - romantisch",
        "start_dt": datetime(2026, 8, 24, 21, 30, tzinfo=TZ),
    }
    ctx = _context()
    update = _update("1", chat_id=222)

    with patch("app.bot.schedule_intimacy_event") as mock_schedule:
        await receive_sex_confirmation(update, ctx)

    mock_schedule.assert_called_once()
    kwargs = mock_schedule.call_args.kwargs
    assert kwargs["title"] == "Wir zwei - romantisch"
    assert kwargs["start_dt"].isoformat() == "2026-08-24T21:30:00+02:00"
    assert kwargs["end_dt"].isoformat() == "2026-08-24T22:30:00+02:00"
    assert 222 not in PENDING_SEX_PROPOSALS
    assert "Im Kalender gespeichert" in update.message.reply_text.await_args.args[0]
    assert "Bestätigt" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_sex_confirmation_vielleicht_saves_calendar(chat_ids):
    PENDING_SEX_PROPOSALS.clear()
    PENDING_SEX_PROPOSALS[222] = {
        "proposer_chat_id": 111,
        "title": "Wir zwei - sanft",
        "start_dt": datetime(2026, 8, 24, 21, 30, tzinfo=TZ),
    }
    ctx = _context()
    update = _update("3", chat_id=222)

    with patch("app.bot.schedule_intimacy_event") as mock_schedule:
        await receive_sex_confirmation(update, ctx)

    mock_schedule.assert_called_once()
    assert 222 not in PENDING_SEX_PROPOSALS
    assert "vielleicht" in update.message.reply_text.await_args.args[0].lower()


async def test_sex_confirmation_2_does_not_save_calendar(chat_ids):
    PENDING_SEX_PROPOSALS.clear()
    PENDING_SEX_PROPOSALS[222] = {
        "proposer_chat_id": 111,
        "title": "Wir zwei - sanft",
        "start_dt": datetime(2026, 8, 24, 21, 30, tzinfo=TZ),
    }
    ctx = _context()
    update = _update("2", chat_id=222)

    with patch("app.bot.schedule_intimacy_event") as mock_schedule:
        await receive_sex_confirmation(update, ctx)

    mock_schedule.assert_not_called()
    assert 222 not in PENDING_SEX_PROPOSALS
    assert "Alles klar" in update.message.reply_text.await_args.args[0]
    assert "Ein andermal" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_sex_missing_cycle_calendar_id_reports_error_after_confirmation(chat_ids):
    PENDING_SEX_PROPOSALS.clear()
    PENDING_SEX_PROPOSALS[222] = {
        "proposer_chat_id": 111,
        "title": "Wir zwei - sanft",
        "start_dt": datetime(2026, 8, 24, 21, 30, tzinfo=TZ),
    }
    ctx = _context()
    update = _update("Ja", chat_id=222)

    with patch("app.bot.schedule_intimacy_event", side_effect=CycleError("CYCLE_GOOGLE_CALENDAR_ID ist nicht konfiguriert.")):
        await receive_sex_confirmation(update, ctx)

    assert "CYCLE_GOOGLE_CALENDAR_ID" in update.message.reply_text.await_args.args[0]
    assert 222 in PENDING_SEX_PROPOSALS
