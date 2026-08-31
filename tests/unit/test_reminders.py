from datetime import date
from unittest.mock import MagicMock, patch

from app.reminders import (
    REMINDER_MISFIRE_GRACE_SECONDS,
    daily_reminder,
    format_daily_message,
    format_weekly_message,
    register_jobs,
    weekly_reminder,
)


def _event(title: str, start: str) -> dict:
    return {"title": title, "start": start, "end": start, "location": ""}


def test_daily_message_with_events():
    events = [
        _event("Arzttermin", "2026-06-04T09:00:00+02:00"),
        _event("Schule abholen", "2026-06-04T15:30:00+02:00"),
    ]
    msg = format_daily_message(events, date(2026, 6, 4))
    assert msg.startswith("Guten Morgen!")
    assert "Arzttermin" in msg
    assert "Schule abholen" in msg
    assert "09:00" in msg
    assert "15:30" in msg


def test_daily_message_empty():
    msg = format_daily_message([], date(2026, 6, 4))
    assert "Heute keine Termine." in msg


def test_daily_message_contains_formatted_date():
    msg = format_daily_message([], date(2026, 6, 3))  # Wednesday
    assert "Mittwoch" in msg
    assert "03.06.2026" in msg


def test_weekly_message_with_events():
    events = [
        _event("Meeting", "2026-06-01T10:00:00+02:00"),
        _event("Sport", "2026-06-03T18:00:00+02:00"),
    ]
    msg = format_weekly_message(events)
    assert msg.startswith("Gute Woche!")
    assert "Meeting" in msg
    assert "Sport" in msg


def test_weekly_message_empty():
    msg = format_weekly_message([])
    assert "Diese Woche keine Termine." in msg


def test_weekly_message_day_headers_in_german():
    events = [_event("Test", "2026-06-01T10:00:00+02:00")]  # Monday
    msg = format_weekly_message(events)
    assert "Montag" in msg
    assert "01.06.2026" in msg


def test_weekly_message_multiple_days():
    events = [
        _event("Event A", "2026-06-01T09:00:00+02:00"),  # Monday
        _event("Event B", "2026-06-03T14:00:00+02:00"),  # Wednesday
        _event("Event C", "2026-06-05T11:00:00+02:00"),  # Friday
    ]
    msg = format_weekly_message(events)
    assert "Montag" in msg
    assert "Mittwoch" in msg
    assert "Freitag" in msg
    assert "Event A" in msg
    assert "Event B" in msg
    assert "Event C" in msg
    assert msg.index("Montag") < msg.index("Mittwoch") < msg.index("Freitag")


def test_register_jobs_sets_misfire_grace_time():
    scheduler = MagicMock()
    bot = MagicMock()

    with patch("app.reminders.get_scheduler", return_value=scheduler):
        register_jobs(bot)

    assert scheduler.add_job.call_count == 2
    daily_call, weekly_call = scheduler.add_job.call_args_list
    assert daily_call.args[:2] == (daily_reminder, "cron")
    assert daily_call.kwargs["misfire_grace_time"] == REMINDER_MISFIRE_GRACE_SECONDS
    assert weekly_call.args[:2] == (weekly_reminder, "cron")
    assert weekly_call.kwargs["day_of_week"] == "mon"
    assert weekly_call.kwargs["misfire_grace_time"] == REMINDER_MISFIRE_GRACE_SECONDS
