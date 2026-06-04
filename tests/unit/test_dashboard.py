from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


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


def test_dashboard_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_dashboard_contains_panel_ids(client):
    body = client.get("/").text
    assert "panel-heute" in body
    assert "panel-woche" in body
    assert "panel-einkauf" in body


def test_dashboard_contains_htmx(client):
    body = client.get("/").text
    assert "hx-get" in body
