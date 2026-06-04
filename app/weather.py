import os

import httpx

_BASE = "http://api.open-meteo.com/v1/forecast"

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


def get_forecast(days: int = 5) -> list[dict]:
    lat = os.environ.get("WEATHER_LAT", "").strip()
    lon = os.environ.get("WEATHER_LON", "").strip()
    if not lat or not lon:
        return []

    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "timezone": "Europe/Zurich",
        "forecast_days": days + 1,  # index 0 = today; we return 1..days
    }
    elev = os.environ.get("WEATHER_ELEVATION", "").strip()
    if elev:
        params["elevation"] = elev

    r = httpx.get(_BASE, params=params, timeout=15)
    r.raise_for_status()
    daily = r.json()["daily"]

    result = []
    for i in range(0, days):
        code = daily["weather_code"][i]
        emoji, description = _WMO.get(code, ("🌡️", "Unbekannt"))
        result.append({
            "date": daily["time"][i],           # "YYYY-MM-DD"
            "emoji": emoji,
            "description": description,
            "temp_min": round(daily["temperature_2m_min"][i]),
            "temp_max": round(daily["temperature_2m_max"][i]),
        })
    return result


def get_weather() -> dict | None:
    lat = os.environ.get("WEATHER_LAT", "").strip()
    lon = os.environ.get("WEATHER_LON", "").strip()
    if not lat or not lon:
        return None

    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,weather_code",
        "daily": "temperature_2m_max",
        "timezone": "Europe/Zurich",
    }
    elev = os.environ.get("WEATHER_ELEVATION", "").strip()
    if elev:
        params["elevation"] = elev

    r = httpx.get(_BASE, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    current = data["current"]

    emoji, description = _WMO.get(current["weather_code"], ("🌡️", "Unbekannt"))
    daily_max = data["daily"]["temperature_2m_max"]
    return {
        "temp": round(current["temperature_2m"]),
        "feels_like": round(current["apparent_temperature"]),
        "temp_max": round(daily_max[0]),
        "description": description,
        "emoji": emoji,
    }
