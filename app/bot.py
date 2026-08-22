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

from app.gcalendar import create_event, get_events_range
from app.cycle import (
    CycleError,
    cycle_intervals,
    get_cycle_starts,
    predict_next_cycle,
    record_cycle_start,
    replace_predicted_cycle_event,
    schedule_intimacy_event,
)
from app.llm_events import LLMEventError, ParsedEvent, parse_natural_event
from app.notes import add_note
from app.meals import get_plan, set_meal, delete_meal, get_meal_list, add_to_meal_list

TZ = ZoneInfo("Europe/Zurich")

# Conversation states
DATE_TITLE, TITLE, TIME_STATE, DURATION, DESCRIPTION, CONFIRM = range(6)
NL_CONFIRM = 6
SEX_STYLE = 7


class DurationResult(NamedTuple):
    delta: timedelta | None
    all_day: bool


def _chat_id_from_env(key: str) -> int | None:
    value = os.environ.get(key, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid Telegram chat ID in %s", key)
        return None


def _notification_target_chat_id(creator_chat_id: int | None) -> int | None:
    if creator_chat_id is None:
        return None
    chat_1 = _chat_id_from_env("TELEGRAM_CHAT_ID_1")
    chat_2 = _chat_id_from_env("TELEGRAM_CHAT_ID_2")
    if creator_chat_id == chat_1:
        return chat_2
    if creator_chat_id == chat_2:
        return chat_1
    return None


def _sender_name(update: Update) -> str:
    user = getattr(update, "effective_user", None)
    name = getattr(user, "first_name", None)
    return name or "jemand"


SEX_STYLES = ["romantisch", "sanft", "impulsiv", "schmutzig", "Überraschung"]
SEX_STYLE_ALIASES = {str(i): style for i, style in enumerate(SEX_STYLES, start=1)} | {
    style.lower(): style for style in SEX_STYLES
} | {"ueberraschung": "Überraschung"}
SEX_STYLE_PROMPT = "Welcher Stil?\n1 romantisch\n2 sanft\n3 impulsiv\n4 schmutzig\n5 Überraschung"
PENDING_SEX_PROPOSALS: dict[int, dict] = {}


def _parse_sex_style(text: str) -> str | None:
    return SEX_STYLE_ALIASES.get(text.strip().lower())


def _sex_title(style: str) -> str:
    return f"Wir zwei - {style}"


def _format_intimacy_when(start_dt: datetime) -> str:
    return start_dt.astimezone(TZ).strftime("%d.%m.%Y, %H:%M")


def _format_intimacy_notification(title: str, start_dt: datetime) -> str:
    return (
        f"❤️ Zeit zu zweit vorgeschlagen\n{title}\n{_format_intimacy_when(start_dt)}\n"
        "Antwort: Ja, heute nicht oder vielleicht"
    )


def _format_event_when(start_dt: datetime, end_dt: datetime, all_day: bool) -> str:
    if all_day:
        if end_dt.date() > start_dt.date():
            return f"{start_dt.strftime('%d.%m.%Y')}-{end_dt.strftime('%d.%m.%Y')}, ganztägig"
        return f"{start_dt.strftime('%d.%m.%Y')}, ganztägig"
    if end_dt.date() > start_dt.date():
        return (
            f"{start_dt.strftime('%d.%m.%Y %H:%M')}-"
            f"{end_dt.strftime('%d.%m.%Y %H:%M')}"
        )
    return f"{start_dt.strftime('%d.%m.%Y')}, {start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"


def _format_event_notification(
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    all_day: bool,
    creator_name: str,
) -> str:
    return (
        f"📅 Neuer Termin von {creator_name}\n"
        f"{title}\n"
        f"{_format_event_when(start_dt, end_dt, all_day)}"
    )


async def _notify_other_about_event(
    update: Update,
    context,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    all_day: bool = False,
) -> None:
    chat = getattr(update, "effective_chat", None)
    target_chat_id = _notification_target_chat_id(getattr(chat, "id", None))
    if target_chat_id is None:
        return

    bot = getattr(context, "bot", None)
    if bot is None:
        logger.info("Skipping event notification because context.bot is unavailable")
        return

    try:
        await bot.send_message(
            chat_id=target_chat_id,
            text=_format_event_notification(
                title=title,
                start_dt=start_dt,
                end_dt=end_dt,
                all_day=all_day,
                creator_name=_sender_name(update),
            ),
        )
    except Exception as exc:
        logger.error("Failed to send event notification: %s", exc)


# ---------------------------------------------------------------------------
# Pure parse helpers — no Telegram dependency, fully unit-testable
# ---------------------------------------------------------------------------

def parse_date_and_title(text: str) -> tuple[date, str | None]:
    """Parse 'TT.MM[.JJJJ] [optionaler Titel]' — returns (date, title or None)."""
    parts = text.strip().split(None, 1)
    parsed = parse_date(parts[0])
    title = parts[1].strip() if len(parts) > 1 else None
    return parsed, title


def parse_date(text: str) -> date:
    parts = [p for p in text.strip().split(".") if p]  # strip trailing dot, ignore empty
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
    if not re.match(r"^\d{1,2}:\d{2}$", text):
        raise ValueError(f"Ungültiges Zeitformat: {text!r}")
    h, m = text.split(":")
    try:
        return time(int(h), int(m))
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
    if not context.args:
        await update.message.reply_text(
            "Datum eingeben (TT.MM oder TT.MM.JJJJ), optional gefolgt vom Titel:\n"
            "Beispiel: 25.12 Familien-Weihnachten"
        )
        return DATE_TITLE

    # Inline format: /event D.M. HH:MM Titel
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Format: /event TT.MM HH:MM Titel\n"
            "Beispiel: /event 5.6. 14:30 Zahnarzt\n\n"
            "Oder einfach /event für den geführten Dialog."
        )
        return ConversationHandler.END

    try:
        event_date = parse_date(args[0])
    except ValueError:
        await update.message.reply_text("❌ Ungültiges Datum. Format: TT.MM oder TT.MM.JJJJ")
        return ConversationHandler.END

    try:
        event_time = parse_time(args[1])
    except ValueError:
        await update.message.reply_text("❌ Ungültige Uhrzeit. Format: HH:MM oder H:MM")
        return ConversationHandler.END

    title = " ".join(args[2:]).strip()
    start_dt = datetime.combine(event_date, event_time, tzinfo=TZ)
    end_dt = start_dt + timedelta(hours=1)

    try:
        create_event(title=title, start_dt=start_dt, end_dt=end_dt)
        await update.message.reply_text(
            f"✅ Termin gespeichert!\n"
            f"📅 {event_date.strftime('%d.%m.%Y')} um {event_time.strftime('%H:%M')}\n"
            f"📌 {title}"
        )
        await _notify_other_about_event(update, context, title, start_dt, end_dt)
    except Exception as exc:
        logger.error("create_event failed: %s", exc)
        await update.message.reply_text("❌ Fehler beim Speichern des Termins.")

    return ConversationHandler.END


async def receive_date_and_title(update: Update, context) -> int:
    try:
        event_date, title = parse_date_and_title(update.message.text)
    except ValueError:
        await update.message.reply_text(
            "❌ Ungültiges Datum. Bitte im Format TT.MM oder TT.MM.JJJJ eingeben (z.B. 25.12):"
        )
        return DATE_TITLE
    context.user_data["date"] = event_date
    if title:
        context.user_data["title"] = title
        await update.message.reply_text("Um wie viel Uhr? (Format: HH:MM)")
        return TIME_STATE
    await update.message.reply_text("Wie soll der Termin heißen?")
    return TITLE


async def receive_title(update: Update, context) -> int:
    context.user_data["title"] = update.message.text.strip()
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
        await _notify_other_about_event(
            update,
            context,
            d["title"],
            start_dt,
            end_dt,
            all_day=duration.all_day,
        )
        context.user_data.clear()
        return ConversationHandler.END

    if answer == "nein":
        await update.message.reply_text("❌ Abgebrochen.")
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text("Bitte mit Ja oder Nein antworten.")
    return CONFIRM


def _format_parsed_event(event: ParsedEvent) -> str:
    if event.end_dt.date() > event.start_dt.date():
        date_info = f"{event.start_dt.strftime('%d.%m.%Y')} – {event.end_dt.strftime('%d.%m.%Y')}"
    else:
        date_info = event.start_dt.strftime('%d.%m.%Y')
    if event.all_day:
        time_info = "Ganzer Tag"
    else:
        time_info = f"{event.start_dt.strftime('%H:%M')} – {event.end_dt.strftime('%H:%M')}"
    desc_line = f"\nBeschreibung: {event.description}" if event.description else ""
    return (
        f"📋 Erkannt:\n"
        f"Titel: {event.title}\n"
        f"Datum: {date_info}\n"
        f"Zeit: {time_info}"
        f"{desc_line}\n\n"
        f"Termin speichern? (Ja / Nein)"
    )


async def _start_natural_event(update: Update, context, text: str) -> int:
    text = text.strip()
    if not text:
        await update.message.reply_text(
            "Bitte beschreibe den Termin, z.B.:\n"
            "/eventnl Morgen 14:30 Zahnarzt"
        )
        return ConversationHandler.END

    try:
        parsed = parse_natural_event(text)
    except LLMEventError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return ConversationHandler.END
    except Exception as exc:
        logger.error("parse_natural_event failed: %s", exc)
        await update.message.reply_text("❌ Ich konnte den Termin gerade nicht auswerten.")
        return ConversationHandler.END

    context.user_data["nl_event"] = parsed
    await update.message.reply_text(_format_parsed_event(parsed))
    return NL_CONFIRM


async def cmd_eventnl(update: Update, context) -> int:
    return await _start_natural_event(update, context, " ".join(context.args))


async def receive_natural_event(update: Update, context) -> int:
    return await _start_natural_event(update, context, update.message.text)


async def receive_natural_confirm(update: Update, context) -> int:
    answer = update.message.text.strip().lower()
    if answer == "ja":
        event: ParsedEvent | None = context.user_data.get("nl_event")
        if not event:
            await update.message.reply_text("❌ Kein Termin zwischengespeichert.")
            return ConversationHandler.END
        try:
            create_event(
                title=event.title,
                start_dt=event.start_dt,
                end_dt=event.end_dt,
                description=event.description,
                all_day=event.all_day,
            )
            await update.message.reply_text("✅ Termin gespeichert!")
            await _notify_other_about_event(
                update,
                context,
                event.title,
                event.start_dt,
                event.end_dt,
                all_day=event.all_day,
            )
        except Exception as exc:
            logger.error("create_event from natural language failed: %s", exc)
            await update.message.reply_text("❌ Fehler beim Speichern des Termins.")
        finally:
            context.user_data.pop("nl_event", None)
        return ConversationHandler.END

    if answer == "nein":
        context.user_data.pop("nl_event", None)
        await update.message.reply_text("❌ Abgebrochen.")
        return ConversationHandler.END

    await update.message.reply_text("Bitte mit Ja oder Nein antworten.")
    return NL_CONFIRM


async def _send_intimacy_proposal(update: Update, context, start_dt: datetime, style: str) -> int:
    chat = getattr(update, "effective_chat", None)
    proposer_chat_id = getattr(chat, "id", None)
    target_chat_id = _notification_target_chat_id(proposer_chat_id)
    if target_chat_id is None:
        await update.message.reply_text("❌ Kein Empfänger konfiguriert.")
        context.user_data.pop("sex_start_dt", None)
        return ConversationHandler.END

    bot = getattr(context, "bot", None)
    if bot is None:
        await update.message.reply_text("❌ Bot ist gerade nicht verfügbar.")
        context.user_data.pop("sex_start_dt", None)
        return ConversationHandler.END

    title = _sex_title(style)
    PENDING_SEX_PROPOSALS[target_chat_id] = {
        "proposer_chat_id": proposer_chat_id,
        "title": title,
        "start_dt": start_dt,
    }
    try:
        await bot.send_message(
            chat_id=target_chat_id,
            text=_format_intimacy_notification(title, start_dt),
        )
    except Exception as exc:
        PENDING_SEX_PROPOSALS.pop(target_chat_id, None)
        logger.error("send intimacy proposal failed: %s", exc)
        await update.message.reply_text("❌ Vorschlag konnte nicht gesendet werden.")
        return ConversationHandler.END
    finally:
        context.user_data.pop("sex_start_dt", None)

    await update.message.reply_text("✅ Vorschlag gesendet.")
    return ConversationHandler.END


async def receive_sex_confirmation(update: Update, context) -> None:
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    proposal = PENDING_SEX_PROPOSALS.get(chat_id)
    if proposal is None:
        return

    answer = update.message.text.strip().lower()
    bot = getattr(context, "bot", None)
    proposer_chat_id = proposal.get("proposer_chat_id")
    if answer == "heute nicht":
        PENDING_SEX_PROPOSALS.pop(chat_id, None)
        await update.message.reply_text("Alles klar.")
        if bot is not None and proposer_chat_id is not None:
            await bot.send_message(chat_id=proposer_chat_id, text="Heute nicht.")
        return

    if answer not in {"ja", "vielleicht"}:
        await update.message.reply_text("Bitte mit Ja, heute nicht oder vielleicht antworten.")
        return

    title = proposal["title"]
    start_dt = proposal["start_dt"]
    end_dt = start_dt + timedelta(hours=1)
    try:
        schedule_intimacy_event(title=title, start_dt=start_dt, end_dt=end_dt)
    except CycleError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    except Exception as exc:
        logger.error("schedule confirmed intimacy appointment failed: %s", exc)
        await update.message.reply_text("❌ Termin konnte nicht gespeichert werden.")
        return

    PENDING_SEX_PROPOSALS.pop(chat_id, None)
    if answer == "ja":
        await update.message.reply_text("✅ Im Kalender gespeichert.")
        notify_text = "✅ Bestätigt und im Kalender gespeichert."
    else:
        await update.message.reply_text("✅ Als vielleicht im Kalender gespeichert.")
        notify_text = "Vielleicht - im Kalender gespeichert."
    if bot is not None and proposer_chat_id is not None:
        await bot.send_message(chat_id=proposer_chat_id, text=notify_text)


async def cmd_sex(update: Update, context) -> int:
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Verwendung: /sex TT.MM HH:MM")
        return ConversationHandler.END

    try:
        event_date = parse_date(args[0])
    except ValueError:
        await update.message.reply_text("❌ Ungültiges Datum. Format: TT.MM oder TT.MM.JJJJ")
        return ConversationHandler.END

    try:
        event_time = parse_time(args[1])
    except ValueError:
        await update.message.reply_text("❌ Ungültige Uhrzeit. Format: HH:MM oder H:MM")
        return ConversationHandler.END

    start_dt = datetime.combine(event_date, event_time, tzinfo=TZ)
    style_text = " ".join(args[2:]).strip()
    if not style_text:
        context.user_data["sex_start_dt"] = start_dt
        await update.message.reply_text(SEX_STYLE_PROMPT)
        return SEX_STYLE

    style = _parse_sex_style(style_text)
    if style is None:
        await update.message.reply_text("Bitte mit 1, 2, 3, 4 oder 5 antworten.")
        return ConversationHandler.END

    return await _send_intimacy_proposal(update, context, start_dt, style)


async def receive_sex_style(update: Update, context) -> int:
    start_dt: datetime | None = context.user_data.get("sex_start_dt")
    if start_dt is None:
        await update.message.reply_text("❌ Kein Vorschlag zwischengespeichert.")
        return ConversationHandler.END

    style = _parse_sex_style(update.message.text)
    if style is None:
        await update.message.reply_text("Bitte mit 1, 2, 3, 4 oder 5 antworten.")
        return SEX_STYLE

    return await _send_intimacy_proposal(update, context, start_dt, style)


async def cmd_cancel(update: Update, context) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Abgebrochen.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def _build_conversation_handler(allowed) -> ConversationHandler:
    cancel = CommandHandler("abbrechen", cmd_cancel)
    return ConversationHandler(
        entry_points=[CommandHandler("event", cmd_neuesevent, filters=allowed)],
        states={
            DATE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_date_and_title), cancel],
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title), cancel],
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


def _build_natural_event_handler(allowed) -> ConversationHandler:
    cancel = CommandHandler("abbrechen", cmd_cancel)
    return ConversationHandler(
        entry_points=[
            CommandHandler("eventnl", cmd_eventnl, filters=allowed),
            MessageHandler(filters.TEXT & ~filters.COMMAND & allowed, receive_natural_event),
        ],
        states={
            NL_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_natural_confirm), cancel],
        },
        fallbacks=[cancel],
    )


def _build_sex_handler(allowed) -> ConversationHandler:
    cancel = CommandHandler("abbrechen", cmd_cancel)
    return ConversationHandler(
        entry_points=[CommandHandler("sex", cmd_sex, filters=allowed)],
        states={
            SEX_STYLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_sex_style), cancel],
        },
        fallbacks=[cancel],
    )


async def _error_handler(update: object, context) -> None:
    logger.error("PTB error", exc_info=context.error)


async def cmd_love(update: Update, context) -> None:
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text('Bitte einen Text angeben, z.B.: /love Ich denke an dich')
        return

    chat = getattr(update, "effective_chat", None)
    target_chat_id = _notification_target_chat_id(getattr(chat, "id", None))
    if target_chat_id is None:
        await update.message.reply_text("❌ Kein Empfänger konfiguriert.")
        return

    bot = getattr(context, "bot", None)
    if bot is None:
        await update.message.reply_text("❌ Bot ist gerade nicht verfügbar.")
        return

    sender = _sender_name(update)
    try:
        await bot.send_message(
            chat_id=target_chat_id,
            text=f"❤️ Liebesnachricht von {sender}:\n{text}",
        )
    except Exception as exc:
        logger.error("Failed to send love message: %s", exc)
        await update.message.reply_text("❌ Liebesnachricht konnte nicht gesendet werden.")
        return

    await update.message.reply_text("❤️ Gesendet.")


async def cmd_note(update: Update, context) -> None:
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Bitte einen Text angeben, z.B.: /note Milch kaufen nicht vergessen")
        return
    author = update.effective_user.first_name or ""
    add_note(text, author)
    await update.message.reply_text(f"📌 Notiz gespeichert: {text}")


async def cmd_meal(update: Update, context) -> None:
    """/meal TT.MM [Mahlzeit] — set or show meal for a date."""
    args = context.args
    if not args:
        await update.message.reply_text("Verwendung:\n/meal TT.MM Mahlzeit — speichern\n/meal TT.MM — anzeigen")
        return
    try:
        day = parse_date(args[0])
    except ValueError:
        await update.message.reply_text("❌ Ungültiges Datum. Format: TT.MM oder TT.MM.JJJJ")
        return
    if len(args) == 1:
        meal = get_plan().get(day.isoformat())
        if meal:
            await update.message.reply_text(f"🍽 {day.strftime('%d.%m.')}: {meal}")
        else:
            await update.message.reply_text(f"Kein Menü für {day.strftime('%d.%m.')} geplant.")
        return
    meal = " ".join(args[1:]).strip()
    set_meal(day, meal)
    add_to_meal_list(meal)
    await update.message.reply_text(f"✅ Menü für {day.strftime('%d.%m.')} gespeichert: {meal}")


async def cmd_delmeal(update: Update, context) -> None:
    """/delmeal TT.MM — remove meal for a date."""
    args = context.args
    if not args:
        await update.message.reply_text("Verwendung: /delmeal TT.MM")
        return
    try:
        day = parse_date(args[0])
    except ValueError:
        await update.message.reply_text("❌ Ungültiges Datum. Format: TT.MM oder TT.MM.JJJJ")
        return
    delete_meal(day)
    await update.message.reply_text(f"🗑 Menü für {day.strftime('%d.%m.')} gelöscht.")


async def cmd_meals(update: Update, context) -> None:
    """/meals — show meal plan for the next 7 days."""
    plan = get_plan()
    today = datetime.now(TZ).date()
    lines = ["📅 Menüplan:"]
    german_days = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    for i in range(7):
        day = today + timedelta(days=i)
        label = "Heute" if i == 0 else german_days[day.weekday()]
        meal = plan.get(day.isoformat(), "–")
        lines.append(f"• {label} {day.strftime('%d.%m.')}: {meal}")
    await update.message.reply_text("\n".join(lines))


async def cmd_period(update: Update, context) -> None:
    """/period [TT.MM|TT.MM.JJJJ] — save cycle start, defaulting to today."""
    args = context.args
    if len(args) > 1:
        await update.message.reply_text("Verwendung: /period oder /period TT.MM")
        return

    if args:
        try:
            day = parse_date(args[0])
        except ValueError:
            await update.message.reply_text("❌ Ungültiges Datum. Format: TT.MM oder TT.MM.JJJJ")
            return
    else:
        day = datetime.now(TZ).date()

    try:
        record_cycle_start(day)
    except CycleError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    except Exception as exc:
        logger.error("record_cycle_start failed: %s", exc)
        await update.message.reply_text("❌ Fehler beim Speichern des Zyklusstarts.")
        return

    await update.message.reply_text(f"✅ Zyklusstart gespeichert: {day.strftime('%d.%m.%Y')}")


async def cmd_periodhistory(update: Update, context) -> None:
    """/periodhistory — show recent cycle starts and intervals."""
    try:
        starts = get_cycle_starts()
    except CycleError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    except Exception as exc:
        logger.error("get_cycle_starts failed: %s", exc)
        await update.message.reply_text("❌ Fehler beim Laden der Zyklushistorie.")
        return

    if not starts:
        await update.message.reply_text("Noch kein Zyklusstart gespeichert.")
        return

    intervals = cycle_intervals(starts)
    recent_starts = starts[-6:]
    lines = ["📅 Zyklushistorie:"]
    for idx, day in enumerate(recent_starts):
        suffix = ""
        global_index = len(starts) - len(recent_starts) + idx
        if global_index > 0:
            suffix = f" ({(starts[global_index] - starts[global_index - 1]).days} Tage)"
        lines.append(f"• {day.strftime('%d.%m.%Y')}{suffix}")
    if intervals:
        avg = int(sum(intervals) / len(intervals) + 0.5)
        lines.append(f"\nDurchschnitt: {avg} Tage")

    await update.message.reply_text("\n".join(lines))


async def cmd_periodnext(update: Update, context) -> None:
    """/periodnext — predict and store next expected cycle start."""
    try:
        prediction = predict_next_cycle()
        replace_predicted_cycle_event(prediction.next_start)
    except CycleError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    except Exception as exc:
        logger.error("period prediction failed: %s", exc)
        await update.message.reply_text("❌ Fehler beim Berechnen des nächsten Zyklusstarts.")
        return

    basis = (
        f"basierend auf {prediction.based_on_cycles} Zyklen"
        if prediction.based_on_cycles
        else "mit 28-Tage-Standardwert"
    )
    await update.message.reply_text(
        f"📅 Erwarteter nächster Zyklusstart: {prediction.next_start.strftime('%d.%m.%Y')}\n"
        f"Intervall: {prediction.interval_days} Tage ({basis})\n"
        "Der erwartete Termin wurde im Zykluskalender gespeichert."
    )


async def cmd_today(update: Update, context) -> None:
    """/today — show all events for today."""
    today = datetime.now(TZ).date()
    start_dt = datetime.combine(today, datetime.min.time()).replace(tzinfo=TZ)
    end_dt = datetime.combine(today, datetime.max.time().replace(microsecond=0)).replace(tzinfo=TZ)

    try:
        events = get_events_range(start_dt, end_dt)
    except Exception as exc:
        logger.error("get_events_range failed: %s", exc)
        await update.message.reply_text("❌ Fehler beim Laden der Termine.")
        return

    if not events:
        await update.message.reply_text(f"📅 Heute keine Termine.")
        return

    lines = [f"📅 *Heute, {today.strftime('%d.%m.')}*"]
    for event in events:
        raw = event["start"]
        if "T" in raw:
            time_str = datetime.fromisoformat(raw).astimezone(TZ).strftime("%H:%M")
        else:
            time_str = "Ganztägig"
        lines.append(f"• {time_str} – {event['title']}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_week(update: Update, context) -> None:
    """/week — show all events in the next 7 days."""
    today = datetime.now(TZ).date()
    end = today + timedelta(days=6)
    start_dt = datetime.combine(today, datetime.min.time()).replace(tzinfo=TZ)
    end_dt = datetime.combine(end, datetime.max.time().replace(microsecond=0)).replace(tzinfo=TZ)

    try:
        events = get_events_range(start_dt, end_dt)
    except Exception as exc:
        logger.error("get_events_range failed: %s", exc)
        await update.message.reply_text("❌ Fehler beim Laden der Termine.")
        return

    german_days = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    by_day: dict[date, list] = {}
    for event in events:
        raw = event["start"]
        if "T" in raw:
            dt = datetime.fromisoformat(raw).astimezone(TZ)
            day, time_str = dt.date(), dt.strftime("%H:%M")
        else:
            day, time_str = date.fromisoformat(raw), "Ganztägig"
        by_day.setdefault(day, []).append((time_str, event["title"]))

    if not by_day:
        await update.message.reply_text("📅 Keine Termine in den nächsten 7 Tagen.")
        return

    lines = ["📅 *Nächste 7 Tage:*"]
    for day in sorted(by_day.keys()):
        label = "Heute" if day == today else german_days[day.weekday()]
        lines.append(f"\n*{label}, {day.strftime('%d.%m.')}*")
        for time_str, title in by_day[day]:
            lines.append(f"• {time_str} – {title}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_help(update: Update, context) -> None:
    await update.message.reply_text(
        "📋 Verfügbare Befehle:\n\n"
        "📅 *Termine*\n"
        "/event — Neuen Termin erstellen\n"
        "/eventnl Text — Termin aus natürlicher Sprache erstellen\n"
        "/today — Termine heute\n"
        "/week — Termine nächste 7 Tage\n"
        "/skip — Beschreibung überspringen\n"
        "/abbrechen — Eingabe abbrechen\n\n"
        "🍽 *Menüplan*\n"
        "/meal TT.MM Mahlzeit — Mahlzeit setzen\n"
        "/meal TT.MM — Mahlzeit anzeigen\n"
        "/delmeal TT.MM — Mahlzeit löschen\n"
        "/meals — Menüplan diese Woche\n\n"
        "📌 *Notizen*\n"
        "/note Text — Notiz speichern\n"
        "/love Text — Liebesnachricht senden\n\n"
        "🌙 *Zyklus*\n"
        "/sex TT.MM HH:MM — Zeit zu zweit vorschlagen\n"
        "/period — Zyklusstart heute speichern\n"
        "/period TT.MM — Zyklusstart für Datum speichern\n"
        "/periodhistory — Zyklushistorie anzeigen\n"
        "/periodnext — Nächsten Zyklusstart berechnen\n\n"
        "🔧 *Sonstiges*\n"
        "/ping — Bot testen\n"
        "/help — Diese Hilfe anzeigen",
        parse_mode="Markdown",
    )


async def cmd_ping(update: Update, context) -> None:
    logger.info("PING received from %s", update.effective_user.id)
    await update.message.reply_text("pong")


def build_application() -> Application:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    # updater(None): we manage polling ourselves to avoid asyncio conflicts with uvicorn
    app = ApplicationBuilder().token(token).updater(None).build()

    # Restrict to known family chat IDs; fall back to open if none are configured
    _ids = [
        int(v) for key in ("TELEGRAM_CHAT_ID_1", "TELEGRAM_CHAT_ID_2")
        if (v := os.environ.get(key, "").strip())
    ]
    allowed = filters.Chat(chat_id=_ids) if _ids else filters.ALL

    app.add_handler(CommandHandler("help", cmd_help, filters=allowed))
    app.add_handler(CommandHandler("ping", cmd_ping, filters=allowed))
    app.add_handler(CommandHandler("love", cmd_love, filters=allowed))
    app.add_handler(CommandHandler("note", cmd_note, filters=allowed))
    app.add_handler(CommandHandler("meal", cmd_meal, filters=allowed))
    app.add_handler(CommandHandler("delmeal", cmd_delmeal, filters=allowed))
    app.add_handler(CommandHandler("meals", cmd_meals, filters=allowed))
    app.add_handler(CommandHandler("period", cmd_period, filters=allowed))
    app.add_handler(CommandHandler("periodhistory", cmd_periodhistory, filters=allowed))
    app.add_handler(CommandHandler("periodnext", cmd_periodnext, filters=allowed))
    app.add_handler(CommandHandler("today", cmd_today, filters=allowed))
    app.add_handler(CommandHandler("week", cmd_week, filters=allowed))
    app.add_handler(MessageHandler(filters.Regex(r"^(?i:ja|heute nicht|vielleicht)$") & allowed, receive_sex_confirmation))
    app.add_handler(_build_conversation_handler(allowed))
    app.add_handler(_build_sex_handler(allowed))
    app.add_handler(_build_natural_event_handler(allowed))
    app.add_error_handler(_error_handler)
    return app
