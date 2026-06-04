import logging
import os
import re
from datetime import date, datetime, time, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.gcalendar import create_event

TZ = ZoneInfo("Europe/Zurich")

# Conversation states
TITLE, DATE, TIME_STATE, DURATION, DESCRIPTION, CONFIRM = range(6)


class DurationResult(NamedTuple):
    delta: timedelta | None
    all_day: bool


# ---------------------------------------------------------------------------
# Pure parse helpers — no Telegram dependency, fully unit-testable
# ---------------------------------------------------------------------------

def parse_date(text: str) -> date:
    parts = text.strip().split(".")
    try:
        if len(parts) == 2:
            day, month = int(parts[0]), int(parts[1])
            year = datetime.now(TZ).year
        elif len(parts) == 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            raise ValueError
        return date(year, month, day)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Ungültiges Datum: {text!r}") from exc


def parse_time(text: str) -> time:
    text = text.strip()
    if not re.match(r"^\d{2}:\d{2}$", text):
        raise ValueError(f"Ungültiges Zeitformat: {text!r}")
    hour, minute = int(text[:2]), int(text[3:])
    try:
        return time(hour, minute)
    except ValueError as exc:
        raise ValueError(f"Ungültige Uhrzeit: {text!r}") from exc


def parse_duration(text: str) -> DurationResult:
    text = text.strip()
    if text.lower() == "ganzer tag":
        return DurationResult(delta=None, all_day=True)
    m = re.match(r"^(\d+)\s*h$", text, re.IGNORECASE)
    if m:
        return DurationResult(delta=timedelta(hours=int(m.group(1))), all_day=False)
    m = re.match(r"^(\d+)\s*min$", text, re.IGNORECASE)
    if m:
        return DurationResult(delta=timedelta(minutes=int(m.group(1))), all_day=False)
    raise ValueError(f"Ungültige Dauer: {text!r}")


# ---------------------------------------------------------------------------
# Conversation handlers
# ---------------------------------------------------------------------------

async def cmd_neuesevent(update: Update, context) -> int:
    await update.message.reply_text("Wie soll der Termin heißen?")
    return TITLE


async def receive_title(update: Update, context) -> int:
    context.user_data["title"] = update.message.text.strip()
    await update.message.reply_text("An welchem Datum? (Format: TT.MM oder TT.MM.JJJJ)")
    return DATE


async def receive_date(update: Update, context) -> int:
    try:
        context.user_data["date"] = parse_date(update.message.text)
    except ValueError:
        await update.message.reply_text(
            "❌ Ungültiges Datum. Bitte im Format TT.MM oder TT.MM.JJJJ eingeben (z.B. 25.12):"
        )
        return DATE
    await update.message.reply_text("Um wie viel Uhr? (Format: HH:MM)")
    return TIME_STATE


async def receive_time(update: Update, context) -> int:
    try:
        context.user_data["time"] = parse_time(update.message.text)
    except ValueError:
        await update.message.reply_text(
            "❌ Ungültige Uhrzeit. Bitte im Format HH:MM eingeben (z.B. 14:30):"
        )
        return TIME_STATE
    await update.message.reply_text(
        "Wie lange dauert der Termin? (z.B. 1h, 90min, oder 'ganzer Tag')"
    )
    return DURATION


async def receive_duration(update: Update, context) -> int:
    try:
        context.user_data["duration"] = parse_duration(update.message.text)
    except ValueError:
        await update.message.reply_text(
            "❌ Ungültige Dauer. Beispiele: 1h, 90min, ganzer Tag"
        )
        return DURATION
    await update.message.reply_text(
        "Optionale Beschreibung? (oder /skip)"
    )
    return DESCRIPTION


async def receive_description(update: Update, context) -> int:
    context.user_data["description"] = update.message.text.strip()
    return await _show_summary(update, context)


async def cmd_skip_description(update: Update, context) -> int:
    context.user_data["description"] = ""
    return await _show_summary(update, context)


async def _show_summary(update: Update, context) -> int:
    d = context.user_data
    duration: DurationResult = d["duration"]
    event_date: date = d["date"]
    event_time: time = d["time"]

    if duration.all_day:
        time_info = "Ganzer Tag"
    else:
        start = datetime.combine(event_date, event_time)
        end = start + duration.delta
        time_info = f"{event_time.strftime('%H:%M')} – {end.strftime('%H:%M')}"

    desc_line = f"\nBeschreibung: {d['description']}" if d.get("description") else ""
    await update.message.reply_text(
        f"📋 Zusammenfassung:\n"
        f"Titel: {d['title']}\n"
        f"Datum: {event_date.strftime('%d.%m.%Y')}\n"
        f"Zeit: {time_info}"
        f"{desc_line}\n\n"
        f"Termin speichern? (Ja / Nein)"
    )
    return CONFIRM


async def receive_confirm(update: Update, context) -> int:
    answer = update.message.text.strip().lower()

    if answer == "ja":
        d = context.user_data
        duration: DurationResult = d["duration"]
        event_date: date = d["date"]
        event_time: time = d["time"]

        start_dt = datetime.combine(event_date, event_time, tzinfo=TZ)
        end_dt = start_dt if duration.all_day else start_dt + duration.delta

        create_event(
            title=d["title"],
            start_dt=start_dt,
            end_dt=end_dt,
            description=d.get("description", ""),
            all_day=duration.all_day,
        )
        await update.message.reply_text("✅ Termin gespeichert!")
        context.user_data.clear()
        return ConversationHandler.END

    if answer == "nein":
        await update.message.reply_text("❌ Abgebrochen.")
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text("Bitte mit Ja oder Nein antworten.")
    return CONFIRM


async def cmd_cancel(update: Update, context) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Abgebrochen.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def _build_conversation_handler() -> ConversationHandler:
    cancel = CommandHandler("abbrechen", cmd_cancel)
    return ConversationHandler(
        entry_points=[CommandHandler("event", cmd_neuesevent)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)],
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_date), cancel],
            TIME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_time), cancel],
            DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_duration), cancel],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description),
                CommandHandler("skip", cmd_skip_description),
                cancel,
            ],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_confirm), cancel],
        },
        fallbacks=[cancel],
    )


async def _error_handler(update: object, context) -> None:
    logger.error("PTB error", exc_info=context.error)


async def cmd_ping(update: Update, context) -> None:
    logger.info("PING received from %s", update.effective_user.id)
    await update.message.reply_text("pong")


def build_application() -> Application:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    # updater(None): we manage polling ourselves to avoid asyncio conflicts with uvicorn
    app = ApplicationBuilder().token(token).updater(None).build()
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(_build_conversation_handler())
    app.add_error_handler(_error_handler)
    return app
