from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.cycle import (
    ACTUAL_TITLE,
    PREDICTED_TITLE,
    CycleError,
    cycle_intervals,
    get_cycle_starts,
    predict_next_cycle,
    record_cycle_start,
    replace_predicted_cycle_event,
)

TZ = ZoneInfo("Europe/Zurich")


@pytest.fixture(autouse=True)
def cycle_calendar(monkeypatch):
    monkeypatch.setenv("CYCLE_GOOGLE_CALENDAR_ID", "cycle-calendar")


def test_record_cycle_start_creates_all_day_event():
    with patch("app.cycle.create_event", return_value={"id": "1"}) as mock_create:
        record_cycle_start(date(2026, 8, 15))

    kwargs = mock_create.call_args.kwargs
    assert kwargs["title"] == ACTUAL_TITLE
    assert kwargs["start_dt"].date() == date(2026, 8, 15)
    assert kwargs["all_day"] is True
    assert kwargs["calendar_id"] == "cycle-calendar"


def test_get_cycle_starts_filters_predictions_and_duplicates():
    with patch("app.cycle.get_events_range", return_value=[
        {"title": ACTUAL_TITLE, "start": "2026-06-01", "id": "a"},
        {"title": PREDICTED_TITLE, "start": "2026-06-29", "id": "p"},
        {"title": ACTUAL_TITLE, "start": "2026-06-01", "id": "dup"},
        {"title": ACTUAL_TITLE, "start": "2026-06-29T10:00:00+02:00", "id": "b"},
    ]):
        assert get_cycle_starts(today=date(2026, 7, 1)) == [date(2026, 6, 1), date(2026, 6, 29)]


def test_cycle_intervals():
    assert cycle_intervals([date(2026, 1, 1), date(2026, 1, 30), date(2026, 2, 27)]) == [29, 28]


def test_predict_next_cycle_uses_average_interval():
    with patch("app.cycle.get_cycle_starts", return_value=[
        date(2026, 1, 1),
        date(2026, 1, 30),
        date(2026, 2, 27),
    ]):
        prediction = predict_next_cycle()

    assert prediction.interval_days == 29
    assert prediction.based_on_cycles == 2
    assert prediction.next_start == date(2026, 3, 28)


def test_predict_next_cycle_falls_back_to_28_days():
    with patch("app.cycle.get_cycle_starts", return_value=[date(2026, 1, 1)]):
        prediction = predict_next_cycle()

    assert prediction.interval_days == 28
    assert prediction.based_on_cycles == 0
    assert prediction.next_start == date(2026, 1, 29)


def test_predict_next_cycle_requires_history():
    with patch("app.cycle.get_cycle_starts", return_value=[]):
        with pytest.raises(CycleError, match="kein Zyklusstart"):
            predict_next_cycle()


def test_replace_predicted_cycle_event_deletes_future_predictions_and_creates_one():
    with (
        patch("app.cycle.get_events_range", return_value=[
            {"id": "old", "title": PREDICTED_TITLE, "start": "2026-08-20"},
            {"id": "actual", "title": ACTUAL_TITLE, "start": "2026-08-01"},
        ]),
        patch("app.cycle.delete_event") as mock_delete,
        patch("app.cycle.create_event", return_value={"id": "new"}) as mock_create,
    ):
        replace_predicted_cycle_event(date(2026, 8, 29), today=date(2026, 8, 1))

    mock_delete.assert_called_once_with("old", calendar_id="cycle-calendar")
    kwargs = mock_create.call_args.kwargs
    assert kwargs["title"] == PREDICTED_TITLE
    assert kwargs["start_dt"].date() == date(2026, 8, 29)
    assert kwargs["calendar_id"] == "cycle-calendar"


def test_cycle_calendar_id_required(monkeypatch):
    monkeypatch.setenv("CYCLE_GOOGLE_CALENDAR_ID", "")
    with pytest.raises(CycleError, match="CYCLE_GOOGLE_CALENDAR_ID"):
        record_cycle_start(date(2026, 8, 15))
