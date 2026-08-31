import logging
import os
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegram import Bot

from app.gcalendar import get_events_today, get_events_this_week
from app.scheduler import get_scheduler

TZ = ZoneInfo("Europe/Zurich")
GERMAN_DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

logger = logging.getLogger(__name__)
REMINDER_MISFIRE_GRACE_SECONDS = 300


def _parse_start(event: dict) -> tuple[date, str]:
    raw = event["start"]
    if "T" in raw:
        dt = datetime.fromisoformat(raw).astimezone(TZ)
        return dt.date(), dt.strftime("%H:%M")
    return date.fromisoformat(raw), "ganztägig"


def format_daily_message(events: list[dict], for_date: date) -> str:
    weekday = GERMAN_DAYS[for_date.weekday()]
    date_str = for_date.strftime("%d.%m.%Y")
    header = f"Guten Morgen! 🗓 Heute, {weekday}, {date_str}:\n"

    if not events:
        return header + "Heute keine Termine."

    lines = []
    for event in events:
        _, time_str = _parse_start(event)
        lines.append(f"• {time_str} – {event['title']}")

    return header + "\n".join(lines)


def format_weekly_message(events: list[dict]) -> str:
    header = "Gute Woche! 📅 Diese Woche:\n"

    if not events:
        return header + "Diese Woche keine Termine."

    by_day: dict[date, list] = defaultdict(list)
    for event in events:
        day, time_str = _parse_start(event)
        by_day[day].append((time_str, event["title"]))

    lines = []
    for day in sorted(by_day.keys()):
        weekday = GERMAN_DAYS[day.weekday()]
        date_str = day.strftime("%d.%m.%Y")
        lines.append(f"*{weekday}, {date_str}*")
        for time_str, title in by_day[day]:
            lines.append(f"• {time_str} – {title}")

    return header + "\n".join(lines)


async def _send_to_both(bot: Bot, message: str) -> None:
    for env_key in ("TELEGRAM_CHAT_ID_1", "TELEGRAM_CHAT_ID_2"):
        chat_id = os.environ.get(env_key, "").strip()
        if chat_id:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")


async def _notify_error(bot: Bot, job_name: str, exc: Exception) -> None:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID_1", "").strip()
    if not chat_id:
        return
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Homeapp Fehler in {job_name}: {exc}",
        )
    except Exception as notify_exc:
        logger.error("Failed to send error notification: %s", notify_exc)


async def daily_reminder(bot: Bot) -> None:
    try:
        events = get_events_today()
        msg = format_daily_message(events, datetime.now(TZ).date())
        await _send_to_both(bot, msg)
    except Exception as exc:
        logger.error("daily_reminder failed: %s", exc)
        await _notify_error(bot, "daily_reminder", exc)


async def weekly_reminder(bot: Bot) -> None:
    try:
        events = get_events_this_week()
        msg = format_weekly_message(events)
        await _send_to_both(bot, msg)
    except Exception as exc:
        logger.error("weekly_reminder failed: %s", exc)
        await _notify_error(bot, "weekly_reminder", exc)


def register_jobs(bot: Bot) -> None:
    scheduler = get_scheduler()
    scheduler.add_job(
        daily_reminder,
        "cron",
        hour=6,
        minute=0,
        args=[bot],
        id="daily_reminder",
        misfire_grace_time=REMINDER_MISFIRE_GRACE_SECONDS,
    )
    scheduler.add_job(
        weekly_reminder,
        "cron",
        day_of_week="mon",
        hour=6,
        minute=0,
        args=[bot],
        id="weekly_reminder",
        misfire_grace_time=REMINDER_MISFIRE_GRACE_SECONDS,
    )
