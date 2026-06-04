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


@pytest.fixture(autouse=True)
def clear_grocery_state():
    import app.main
    app.main._checked_items.clear()
    app.main._item_cache.clear()


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


def test_week_endpoint_has_seven_days(client):
    with patch("app.main.get_events_this_week", return_value=[]):
        r = client.get("/api/week")
    assert len(r.json()["days"]) == 7


GROCERY_ITEMS = [
    {"id": "1", "content": "Milch"},
    {"id": "2", "content": "Butter"},
]


def test_grocery_endpoint_returns_list(client):
    with patch("app.main.get_restock_items", return_value=GROCERY_ITEMS):
        r = client.get("/api/grocery")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_grocery_endpoint_empty(client):
    with patch("app.main.get_restock_items", return_value=[]):
        r = client.get("/api/grocery")
    assert r.json() == []


def test_grocery_endpoint_item_format(client):
    with patch("app.main.get_restock_items", return_value=GROCERY_ITEMS):
        r = client.get("/api/grocery")
    for item in r.json():
        assert {"id", "content"} <= item.keys()


def test_toggle_grocery_checks_item(client):
    with patch("app.main.get_restock_items", return_value=GROCERY_ITEMS):
        client.get("/api/grocery", headers={"HX-Request": "true"})
    r = client.post("/api/grocery/1/toggle")
    assert r.status_code == 200
    assert "line-through" in r.text
    assert "✓" in r.text


def test_toggle_grocery_unchecks_item(client):
    with patch("app.main.get_restock_items", return_value=GROCERY_ITEMS):
        client.get("/api/grocery", headers={"HX-Request": "true"})
    client.post("/api/grocery/1/toggle")
    r = client.post("/api/grocery/1/toggle")
    assert "line-through" not in r.text
