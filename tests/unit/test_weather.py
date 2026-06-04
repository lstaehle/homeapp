import pytest
import respx
import httpx


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("WEATHER_LAT", "46.729")
    monkeypatch.setenv("WEATHER_LON", "9.443")


def _mock_response(temp=18.0, feels_like=16.5, code=0):
    return httpx.Response(200, json={
        "current": {
            "temperature_2m": temp,
            "apparent_temperature": feels_like,
            "weather_code": code,
        }
    })


@respx.mock
def test_get_weather_returns_dict():
    respx.get("https://api.open-meteo.com/v1/forecast").mock(return_value=_mock_response(18.4, 17.1, 0))
    from app.weather import get_weather
    w = get_weather()
    assert w["temp"] == 18
    assert w["feels_like"] == 17
    assert w["emoji"] == "☀️"
    assert w["description"] == "Klar"


@respx.mock
def test_get_weather_rain_emoji():
    respx.get("https://api.open-meteo.com/v1/forecast").mock(return_value=_mock_response(12.0, 10.0, 63))
    from app.weather import get_weather
    w = get_weather()
    assert w["emoji"] == "🌧️"
    assert w["description"] == "Regen"


@respx.mock
def test_get_weather_snow_emoji():
    respx.get("https://api.open-meteo.com/v1/forecast").mock(return_value=_mock_response(0.0, -2.0, 73))
    from app.weather import get_weather
    w = get_weather()
    assert w["emoji"] == "❄️"


def test_get_weather_returns_none_without_lat(monkeypatch):
    monkeypatch.setenv("WEATHER_LAT", "")
    from app.weather import get_weather
    assert get_weather() is None


def test_get_weather_returns_none_without_lon(monkeypatch):
    monkeypatch.setenv("WEATHER_LON", "")
    from app.weather import get_weather
    assert get_weather() is None
