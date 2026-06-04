from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

TODAY_EVENT = {
    "title": "Arzttermin",
    "start": "2026-06-04T09:00:00+02:00",
    "end": "2026-06-04T10:00:00+02:00",
    "location": "Praxis Muster",
}

WEEK_EVENT = {
    "title": "Meeting",
    "start": "2026-06-01T10:00:00+02:00",
    "end": "2026-06-01T11:00:00+02:00",
    "location": "",
}


@pytest.fixture
def client():
    mock_bot_app = AsyncMock()
    mock_bot_app.updater = AsyncMock()
    mock_bot_app.bot = MagicMock()

    with (
        patch("app.main.build_application", return_value=mock_bot_app),
        patch("app.main.register_jobs"),
        patch("app.main.get_scheduler", return_value=MagicMock()),
    ):
        with TestClient(app) as c:
            yield c


def test_today_endpoint_structure(client):
    with patch("app.main.get_events_today", return_value=[]):
        r = client.get("/api/today")
    assert r.status_code == 200
    data = r.json()
    assert "date" in data
    assert isinstance(data["date"], str)
    assert "events" in data
    assert isinstance(data["events"], list)


def test_today_endpoint_event_fields(client):
    with patch("app.main.get_events_today", return_value=[TODAY_EVENT]):
        r = client.get("/api/today")
    events = r.json()["events"]
    assert len(events) == 1
    assert {"title", "time", "location"} <= events[0].keys()


def test_today_endpoint_empty_calendar(client):
    with patch("app.main.get_events_today", return_value=[]):
        r = client.get("/api/today")
    data = r.json()
    assert data["events"] == []
    assert "date" in data


def test_week_endpoint_structure(client):
    with patch("app.main.get_events_this_week", return_value=[]):
        r = client.get("/api/week")
    assert r.status_code == 200
    data = r.json()
    assert "days" in data
    for day in data["days"]:
        assert {"date", "weekday", "events"} <= day.keys()


def test_week_endpoint_excludes_today(client):
    with patch("app.main.get_events_this_week", return_value=[]):
        r = client.get("/api/week")
    from datetime import date
    import app.main as m
    today_str = __import__("datetime").datetime.now(m.TZ).date().strftime("%d.%m.%Y")
    dates = [d["date"] for d in r.json()["days"]]
    assert today_str not in dates
    assert len(dates) <= 6


GROCERY_GROUPS = [
    {"section": "Getränke", "items": [{"id": "1", "content": "Milch"}]},
    {"section": None, "items": [{"id": "2", "content": "Butter"}]},
]


def test_grocery_endpoint_returns_list(client):
    with patch("app.main.get_restock_items", return_value=GROCERY_GROUPS):
        r = client.get("/api/grocery")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_grocery_endpoint_empty(client):
    with patch("app.main.get_restock_items", return_value=[]):
        r = client.get("/api/grocery")
    assert r.json() == []


def test_grocery_endpoint_shows_section_headers(client):
    with patch("app.main.get_restock_items", return_value=GROCERY_GROUPS):
        r = client.get("/api/grocery", headers={"HX-Request": "true"})
    assert "Getränke" in r.text
    assert "Milch" in r.text
    assert "Butter" in r.text


def test_complete_grocery_removes_item(client):
    with patch("app.main.complete_task") as mock_complete:
        r = client.post("/api/grocery/42/complete")
    assert r.status_code == 200
    assert r.text == ""
    mock_complete.assert_called_once_with("42")
