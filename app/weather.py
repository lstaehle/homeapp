import os

import httpx

_BASE = "https://api.openweathermap.org/data/2.5/weather"

_EMOJI = {
    range(200, 300): "⛈️",
    range(300, 400): "🌦️",
    range(500, 600): "🌧️",
    range(600, 700): "❄️",
    range(700, 800): "🌫️",
    range(800, 801): "☀️",
    range(801, 802): "🌤️",
    range(802, 803): "⛅",
    range(803, 900): "☁️",
}


def _weather_emoji(condition_id: int) -> str:
    for r, emoji in _EMOJI.items():
        if condition_id in r:
            return emoji
    return "🌡️"


def get_weather() -> dict | None:
    api_key = os.environ.get("OPENWEATHERMAP_API_KEY", "").strip()
    city = os.environ.get("WEATHER_CITY", "").strip()
    if not api_key or not city:
        return None

    r = httpx.get(
        _BASE,
        params={"q": city, "appid": api_key, "units": "metric", "lang": "de"},
        timeout=5,
    )
    r.raise_for_status()
    data = r.json()

    condition = data["weather"][0]
    return {
        "temp": round(data["main"]["temp"]),
        "feels_like": round(data["main"]["feels_like"]),
        "description": condition["description"].capitalize(),
        "emoji": _weather_emoji(condition["id"]),
    }
