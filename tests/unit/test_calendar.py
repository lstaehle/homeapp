from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

TZ = ZoneInfo("Europe/Zurich")


def _make_event(summary="Test", start_dt="2026-06-04T09:00:00+02:00",
                end_dt="2026-06-04T10:00:00+02:00", location=None) -> dict:
    event = {
        "summary": summary,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt},
    }
    if location is not None:
        event["location"] = location
    return event


def _mock_service(items: list) -> MagicMock:
    service = MagicMock()
    service.events().list().execute.return_value = {"items": items}
    return service


@patch("app.gcalendar._get_service")
def test_get_events_today_returns_list(mock_get_service):
    mock_get_service.return_value = _mock_service([
        _make_event("Arzttermin", location="Praxis Muster"),
        _make_event("Schule abholen"),
    ])

    from app.gcalendar import get_events_today

    result = get_events_today()

    assert isinstance(result, list)
    assert len(result) == 2
    for event in result:
        assert set(event.keys()) >= {"title", "start", "end", "location"}


@patch("app.gcalendar._get_service")
def test_get_events_today_empty(mock_get_service):
    mock_get_service.return_value = _mock_service([])

    from app.gcalendar import get_events_today

    assert get_events_today() == []


@patch("app.gcalendar._get_service")
def test_get_events_this_week_time_range(mock_get_service):
    service = MagicMock()
    captured = {}

    def fake_list(**kwargs):
        captured.update(kwargs)
        mock_result = MagicMock()
        mock_result.execute.return_value = {"items": []}
        return mock_result

    service.events().list = MagicMock(side_effect=fake_list)
    mock_get_service.return_value = service

    from app.gcalendar import get_events_this_week

    get_events_this_week()

    time_min = datetime.fromisoformat(captured["timeMin"])
    time_max = datetime.fromisoformat(captured["timeMax"])

    assert time_min.weekday() == 0, "timeMin should be Monday"
    assert time_min.hour == 0 and time_min.minute == 0
    assert time_max.weekday() == 6, "timeMax should be Sunday"
    assert time_max.hour == 23 and time_max.minute == 59


@patch("app.gcalendar._get_service")
def test_event_with_missing_location(mock_get_service):
    mock_get_service.return_value = _mock_service([
        _make_event("Kein Ort"),  # no location key
    ])

    from app.gcalendar import get_events_today

    result = get_events_today()

    assert result[0]["location"] == ""


@patch("app.gcalendar._get_service")
def test_create_all_day_event_uses_exclusive_end_date(mock_get_service):
    service = MagicMock()
    service.events().insert().execute.return_value = {"id": "event-1"}
    captured = {}

    def fake_insert(**kwargs):
        captured.update(kwargs)
        mock_result = MagicMock()
        mock_result.execute.return_value = {"id": "event-1"}
        return mock_result

    service.events().insert = MagicMock(side_effect=fake_insert)
    mock_get_service.return_value = service

    from app.gcalendar import create_event

    create_event(
        title="Schulfrei",
        start_dt=datetime(2026, 7, 1, tzinfo=TZ),
        end_dt=datetime(2026, 7, 1, tzinfo=TZ),
        all_day=True,
    )

    assert captured["body"]["start"]["date"] == "2026-07-01"
    assert captured["body"]["end"]["date"] == "2026-07-02"


@patch("app.gcalendar._get_service")
def test_create_multi_day_all_day_event_uses_exclusive_end_date(mock_get_service):
    service = MagicMock()
    captured = {}

    def fake_insert(**kwargs):
        captured.update(kwargs)
        mock_result = MagicMock()
        mock_result.execute.return_value = {"id": "event-1"}
        return mock_result

    service.events().insert = MagicMock(side_effect=fake_insert)
    mock_get_service.return_value = service

    from app.gcalendar import create_event

    create_event(
        title="Kurzurlaub",
        start_dt=datetime(2026, 7, 10, tzinfo=TZ),
        end_dt=datetime(2026, 7, 12, tzinfo=TZ),
        all_day=True,
    )

    assert captured["body"]["start"]["date"] == "2026-07-10"
    assert captured["body"]["end"]["date"] == "2026-07-13"


@patch("app.gcalendar._get_service")
def test_get_events_range_uses_explicit_calendar_id(mock_get_service):
    service = MagicMock()
    captured = {}

    def fake_list(**kwargs):
        captured.update(kwargs)
        mock_result = MagicMock()
        mock_result.execute.return_value = {"items": []}
        return mock_result

    service.events().list = MagicMock(side_effect=fake_list)
    mock_get_service.return_value = service

    from app.gcalendar import get_events_range

    get_events_range(
        datetime(2026, 1, 1, tzinfo=TZ),
        datetime(2026, 1, 31, tzinfo=TZ),
        calendar_id="cycle-calendar",
    )

    assert captured["calendarId"] == "cycle-calendar"


@patch("app.gcalendar._get_service")
def test_create_event_uses_explicit_calendar_id(mock_get_service):
    service = MagicMock()
    captured = {}

    def fake_insert(**kwargs):
        captured.update(kwargs)
        mock_result = MagicMock()
        mock_result.execute.return_value = {"id": "event-1"}
        return mock_result

    service.events().insert = MagicMock(side_effect=fake_insert)
    mock_get_service.return_value = service

    from app.gcalendar import create_event

    create_event(
        title="Zyklusstart",
        start_dt=datetime(2026, 8, 15, tzinfo=TZ),
        end_dt=datetime(2026, 8, 15, tzinfo=TZ),
        all_day=True,
        calendar_id="cycle-calendar",
    )

    assert captured["calendarId"] == "cycle-calendar"


@patch("app.gcalendar._get_service")
def test_delete_event_uses_explicit_calendar_id(mock_get_service):
    service = MagicMock()
    captured = {}

    def fake_delete(**kwargs):
        captured.update(kwargs)
        mock_result = MagicMock()
        mock_result.execute.return_value = None
        return mock_result

    service.events().delete = MagicMock(side_effect=fake_delete)
    mock_get_service.return_value = service

    from app.gcalendar import delete_event

    delete_event("event-1", calendar_id="cycle-calendar")

    assert captured == {"calendarId": "cycle-calendar", "eventId": "event-1"}
