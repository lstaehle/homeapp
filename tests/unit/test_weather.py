import pytest
import respx
import httpx


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("OPENWEATHERMAP_API_KEY", "fake-key")
    monkeypatch.setenv("WEATHER_CITY", "Zurich,CH")


@respx.mock
def test_get_weather_returns_dict():
    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json={
            "main": {"temp": 18.4, "feels_like": 17.1},
            "weather": [{"id": 800, "description": "klarer himmel"}],
        })
    )
    from app.weather import get_weather
    w = get_weather()
    assert w["temp"] == 18
    assert w["feels_like"] == 17
    assert w["emoji"] == "☀️"
    assert w["description"] == "Klarer himmel"


@respx.mock
def test_get_weather_rain_emoji():
    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json={
            "main": {"temp": 12.0, "feels_like": 10.0},
            "weather": [{"id": 501, "description": "mäßiger regen"}],
        })
    )
    from app.weather import get_weather
    w = get_weather()
    assert w["emoji"] == "🌧️"


def test_get_weather_returns_none_without_api_key(monkeypatch):
    monkeypatch.setenv("OPENWEATHERMAP_API_KEY", "")
    from app.weather import get_weather
    assert get_weather() is None


def test_get_weather_returns_none_without_city(monkeypatch):
    monkeypatch.setenv("WEATHER_CITY", "")
    from app.weather import get_weather
    assert get_weather() is None
