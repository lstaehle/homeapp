import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.gcalendar import create_event, delete_event, get_events_range

TZ = ZoneInfo("Europe/Zurich")
ACTUAL_TITLE = "Zyklusstart"
PREDICTED_TITLE = "Erwarteter Zyklusstart"
DEFAULT_CYCLE_DAYS = 28
LOOKBACK_DAYS = 5 * 366
PREDICTION_LOOKAHEAD_DAYS = 400


class CycleError(Exception):
    pass


@dataclass(frozen=True)
class CyclePrediction:
    next_start: date
    interval_days: int
    based_on_cycles: int


def _calendar_id() -> str:
    calendar_id = os.environ.get("CYCLE_GOOGLE_CALENDAR_ID", "").strip()
    if not calendar_id:
        raise CycleError("CYCLE_GOOGLE_CALENDAR_ID ist nicht konfiguriert.")
    return calendar_id


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=TZ)


def _day_end(day: date) -> datetime:
    return datetime.combine(day, time.max.replace(microsecond=0), tzinfo=TZ)


def _event_date(event: dict) -> date | None:
    raw = event.get("start", "")
    if not raw:
        return None
    if "T" in raw:
        return datetime.fromisoformat(raw).astimezone(TZ).date()
    return date.fromisoformat(raw)


def _list_cycle_events(start_day: date, end_day: date) -> list[dict]:
    return get_events_range(_day_start(start_day), _day_end(end_day), calendar_id=_calendar_id())


def record_cycle_start(day: date) -> dict:
    return create_event(
        title=ACTUAL_TITLE,
        start_dt=_day_start(day),
        end_dt=_day_start(day),
        description="",
        all_day=True,
        calendar_id=_calendar_id(),
    )


def get_cycle_starts(today: date | None = None) -> list[date]:
    today = today or datetime.now(TZ).date()
    events = _list_cycle_events(today - timedelta(days=LOOKBACK_DAYS), today)
    starts = {
        event_date
        for event in events
        if event.get("title") == ACTUAL_TITLE
        if (event_date := _event_date(event)) is not None
    }
    return sorted(starts)


def cycle_intervals(starts: list[date]) -> list[int]:
    return [(b - a).days for a, b in zip(starts, starts[1:]) if (b - a).days > 0]


def predict_next_cycle(today: date | None = None) -> CyclePrediction:
    starts = get_cycle_starts(today=today)
    if not starts:
        raise CycleError("Noch kein Zyklusstart gespeichert.")

    intervals = cycle_intervals(starts)
    if intervals:
        interval_days = int(sum(intervals) / len(intervals) + 0.5)
    else:
        interval_days = DEFAULT_CYCLE_DAYS

    return CyclePrediction(
        next_start=starts[-1] + timedelta(days=interval_days),
        interval_days=interval_days,
        based_on_cycles=len(intervals),
    )


def replace_predicted_cycle_event(predicted_day: date, today: date | None = None) -> dict:
    today = today or datetime.now(TZ).date()
    calendar_id = _calendar_id()
    events = _list_cycle_events(today, today + timedelta(days=PREDICTION_LOOKAHEAD_DAYS))
    for event in events:
        if event.get("title") == PREDICTED_TITLE and event.get("id"):
            delete_event(event["id"], calendar_id=calendar_id)

    return create_event(
        title=PREDICTED_TITLE,
        start_dt=_day_start(predicted_day),
        end_dt=_day_start(predicted_day),
        description="",
        all_day=True,
        calendar_id=calendar_id,
    )


def schedule_intimacy_event(title: str, start_dt: datetime, end_dt: datetime) -> dict:
    return create_event(
        title=title,
        start_dt=start_dt,
        end_dt=end_dt,
        description="",
        all_day=False,
        calendar_id=_calendar_id(),
    )
