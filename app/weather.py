import os

import httpx

_BASE = "https://api.open-meteo.com/v1/forecast"

_WMO = {
    0:  ("☀️",  "Klar"),
    1:  ("🌤️", "Überwiegend klar"),
    2:  ("⛅",  "Teilweise bewölkt"),
    3:  ("☁️",  "Bewölkt"),
    45: ("🌫️", "Nebel"),
    48: ("🌫️", "Nebel"),
    51: ("🌦️", "Leichter Nieselregen"),
    53: ("🌦️", "Nieselregen"),
    55: ("🌦️", "Starker Nieselregen"),
    61: ("🌧️", "Leichter Regen"),
    63: ("🌧️", "Regen"),
    65: ("🌧️", "Starker Regen"),
    71: ("❄️",  "Leichter Schneefall"),
    73: ("❄️",  "Schneefall"),
    75: ("❄️",  "Starker Schneefall"),
    77: ("❄️",  "Schneekörner"),
    80: ("🌧️", "Leichte Regenschauer"),
    81: ("🌧️", "Regenschauer"),
    82: ("🌧️", "Starke Regenschauer"),
    85: ("❄️",  "Leichte Schneeschauer"),
    86: ("❄️",  "Schneeschauer"),
    95: ("⛈️", "Gewitter"),
    96: ("⛈️", "Gewitter mit Hagel"),
    99: ("⛈️", "Gewitter mit Hagel"),
}


def get_weather() -> dict | None:
    lat = os.environ.get("WEATHER_LAT", "").strip()
    lon = os.environ.get("WEATHER_LON", "").strip()
    if not lat or not lon:
        return None

    r = httpx.get(
        _BASE,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code",
            "timezone": "Europe/Zurich",
        },
        timeout=15,
    )
    r.raise_for_status()
    current = r.json()["current"]

    emoji, description = _WMO.get(current["weather_code"], ("🌡️", "Unbekannt"))
    return {
        "temp": round(current["temperature_2m"]),
        "feels_like": round(current["apparent_temperature"]),
        "description": description,
        "emoji": emoji,
    }
