from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
import httpx

from app.llm_events import LLMEventError, parse_natural_event

TZ = ZoneInfo("Europe/Zurich")


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")


def _response(content: str):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": content}}],
    }
    return response


def test_parse_natural_event_defaults_to_one_hour():
    with patch("app.llm_events.httpx.post", return_value=_response(
        '{"is_event": true, "title": "Zahnarzt", "date": "2026-06-27", '
        '"end_date": null, "start_time": "14:30", "end_time": null, '
        '"all_day": false, "description": ""}'
    )) as mock_post:
        event = parse_natural_event(
            "morgen 14:30 Zahnarzt",
            now=datetime(2026, 6, 26, 9, 0, tzinfo=TZ),
        )

    assert event.title == "Zahnarzt"
    assert event.start_dt.isoformat() == "2026-06-27T14:30:00+02:00"
    assert event.end_dt.isoformat() == "2026-06-27T15:30:00+02:00"
    assert event.all_day is False
    assert mock_post.call_args.kwargs["json"]["model"] == "test-model"


def test_parse_natural_event_all_day():
    with patch("app.llm_events.httpx.post", return_value=_response(
        '{"is_event": true, "title": "Schulfrei", "date": "2026-07-01", '
        '"end_date": null, "start_time": null, "end_time": null, "all_day": true, "description": ""}'
    )):
        event = parse_natural_event("am 1. Juli schulfrei")

    assert event.title == "Schulfrei"
    assert event.start_dt.isoformat() == "2026-07-01T00:00:00+02:00"
    assert event.all_day is True


def test_parse_natural_event_multi_day_all_day():
    with patch("app.llm_events.httpx.post", return_value=_response(
        '{"is_event": true, "title": "Kurzurlaub", "date": "2026-07-10", '
        '"end_date": "2026-07-12", "start_time": null, "end_time": null, '
        '"all_day": true, "description": ""}'
    )):
        event = parse_natural_event("Kurzurlaub vom 10. bis 12. Juli")

    assert event.title == "Kurzurlaub"
    assert event.start_dt.isoformat() == "2026-07-10T00:00:00+02:00"
    assert event.end_dt.isoformat() == "2026-07-12T00:00:00+02:00"
    assert event.all_day is True


def test_parse_natural_event_multi_day_timed():
    with patch("app.llm_events.httpx.post", return_value=_response(
        '{"is_event": true, "title": "Konferenz", "date": "2026-09-01", '
        '"end_date": "2026-09-03", "start_time": "10:00", "end_time": "16:00", '
        '"all_day": false, "description": ""}'
    )):
        event = parse_natural_event("Konferenz von 1. September 10 Uhr bis 3. September 16 Uhr")

    assert event.title == "Konferenz"
    assert event.start_dt.isoformat() == "2026-09-01T10:00:00+02:00"
    assert event.end_dt.isoformat() == "2026-09-03T16:00:00+02:00"
    assert event.all_day is False


def test_parse_natural_event_rejects_non_event():
    with patch("app.llm_events.httpx.post", return_value=_response(
        '{"is_event": false, "title": "", "date": null, '
        '"start_time": null, "end_time": null, "all_day": false, "description": ""}'
    )):
        with pytest.raises(LLMEventError, match="Kein Termin"):
            parse_natural_event("hallo")


def test_parse_natural_event_requires_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(LLMEventError, match="OPENAI_API_KEY"):
        parse_natural_event("morgen Zahnarzt")


def test_parse_natural_event_reports_bad_api_key():
    response = httpx.Response(
        401,
        json={"error": {"message": "Incorrect API key provided"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    with patch("app.llm_events.httpx.post", return_value=response):
        with pytest.raises(LLMEventError, match="API-Key"):
            parse_natural_event("morgen Zahnarzt")


def test_parse_natural_event_reports_quota_error():
    response = httpx.Response(
        429,
        json={"error": {"message": "You exceeded your current quota"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    with patch("app.llm_events.httpx.post", return_value=response):
        with pytest.raises(LLMEventError, match="Guthaben"):
            parse_natural_event("morgen Zahnarzt")


def test_parse_natural_event_reports_network_error():
    with patch("app.llm_events.httpx.post", side_effect=httpx.ConnectError("dns failed")):
        with pytest.raises(LLMEventError, match="nicht erreichbar"):
            parse_natural_event("morgen Zahnarzt")
