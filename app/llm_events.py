import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

TZ = ZoneInfo("Europe/Zurich")


class LLMEventError(Exception):
    pass


@dataclass(frozen=True)
class ParsedEvent:
    title: str
    start_dt: datetime
    end_dt: datetime
    description: str = ""
    all_day: bool = False


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise LLMEventError("Ungültiges Datum in der LLM-Antwort.") from exc


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise LLMEventError("Ungültige Uhrzeit in der LLM-Antwort.") from exc


def _extract_json(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMEventError("Die LLM-Antwort war kein gültiges JSON.") from exc


def _error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or "")[:300]
        if isinstance(error, str):
            return error[:300]
    return str(data)[:300]


def _raise_llm_error_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        detail = _error_detail(exc.response)
        if status == 401:
            raise LLMEventError("OpenAI API-Key wurde abgelehnt. Bitte OPENAI_API_KEY prüfen.") from exc
        if status == 429:
            raise LLMEventError("OpenAI Anfrage-Limit oder Guthaben erreicht. Bitte Billing/Quota prüfen.") from exc
        if status == 400:
            raise LLMEventError(f"OpenAI Anfrage ungültig: {detail}") from exc
        raise LLMEventError(f"OpenAI Fehler {status}: {detail}") from exc


def _payload_to_event(payload: dict) -> ParsedEvent:
    if not payload.get("is_event"):
        raise LLMEventError("Kein Termin erkannt.")

    title = str(payload.get("title") or "").strip()
    if not title:
        raise LLMEventError("Kein Titel erkannt.")

    event_date = _parse_date(payload.get("date"))
    end_date = _parse_date(payload["end_date"]) if payload.get("end_date") else event_date
    if end_date < event_date:
        raise LLMEventError("Enddatum liegt vor dem Startdatum.")
    all_day = bool(payload.get("all_day"))
    description = str(payload.get("description") or "").strip()

    if all_day:
        start_dt = datetime.combine(event_date, time.min, tzinfo=TZ)
        end_dt = datetime.combine(end_date, time.min, tzinfo=TZ)
        return ParsedEvent(title=title, start_dt=start_dt, end_dt=end_dt, description=description, all_day=True)

    start_time = _parse_time(payload.get("start_time"))
    if start_time is None:
        raise LLMEventError("Keine Startzeit erkannt.")

    end_time = _parse_time(payload.get("end_time"))
    start_dt = datetime.combine(event_date, start_time, tzinfo=TZ)
    if end_time is None:
        end_dt = start_dt + timedelta(hours=1)
    else:
        end_dt = datetime.combine(end_date, end_time, tzinfo=TZ)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

    return ParsedEvent(title=title, start_dt=start_dt, end_dt=end_dt, description=description, all_day=False)


def parse_natural_event(text: str, now: datetime | None = None) -> ParsedEvent:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise LLMEventError("OPENAI_API_KEY ist nicht konfiguriert.")

    now = now or datetime.now(TZ)
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    system = (
        "Du extrahierst Kalendereinträge aus deutschen Telegram-Nachrichten. "
        "Antworte ausschließlich als JSON-Objekt mit diesen Feldern: "
        "is_event boolean, title string, date YYYY-MM-DD oder null, end_date YYYY-MM-DD oder null, "
        "start_time HH:MM oder null, end_time HH:MM oder null, "
        "all_day boolean, description string. "
        "Wenn kein klarer Terminwunsch erkennbar ist, setze is_event auf false. "
        "Setze end_date nur, wenn die Nachricht ausdrücklich einen mehrtägigen Termin nennt. "
        "Bei mehrtägigen ganztägigen Terminen ist end_date das letzte inklusive Datum. "
        "Bei Terminen mit Startzeit aber ohne Dauer/Ende lasse end_time null. "
        "Nutze Europe/Zurich und das Referenzdatum für relative Angaben."
    )
    user = (
        f"Referenzdatum: {now.date().isoformat()}\n"
        f"Aktueller Wochentag: {now.strftime('%A')}\n"
        f"Nachricht: {text}"
    )

    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=20,
        )
    except httpx.RequestError as exc:
        raise LLMEventError(f"OpenAI nicht erreichbar: {exc}") from exc

    _raise_llm_error_for_status(response)
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMEventError("Unerwartete Antwort von OpenAI.") from exc
    return _payload_to_event(_extract_json(content))
