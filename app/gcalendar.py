import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
TZ = ZoneInfo("Europe/Zurich")


def _get_service():
    creds = None
    token_file = os.environ["GOOGLE_TOKEN_FILE"]
    credentials_file = os.environ["GOOGLE_CREDENTIALS_FILE"]

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Requires a browser — run locally once to generate token.json
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def _parse_event(event: dict) -> dict:
    start = event["start"].get("dateTime", event["start"].get("date", ""))
    end = event["end"].get("dateTime", event["end"].get("date", ""))
    return {
        "title": event.get("summary", "(Kein Titel)"),
        "start": start,
        "end": end,
        "location": event.get("location", ""),
    }


def get_events_today() -> list[dict]:
    now = datetime.now(TZ)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = now.replace(hour=23, minute=59, second=59, microsecond=0)

    service = _get_service()
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return [_parse_event(e) for e in result.get("items", [])]


def get_events_this_week() -> list[dict]:
    now = datetime.now(TZ)
    monday = now - timedelta(days=now.weekday())
    week_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = (monday + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=0)

    service = _get_service()
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=week_start.isoformat(),
            timeMax=week_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return [_parse_event(e) for e in result.get("items", [])]


def create_event(
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    description: str = "",
    all_day: bool = False,
) -> dict:
    service = _get_service()
    if all_day:
        body = {
            "summary": title,
            "description": description,
            "start": {"date": start_dt.date().isoformat()},
            "end": {"date": start_dt.date().isoformat()},
        }
    else:
        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Zurich"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Zurich"},
        }
    return service.events().insert(calendarId="primary", body=body).execute()


def smoke_test():
    from dotenv import load_dotenv

    load_dotenv()
    print("Lade heutige Termine …")
    events = get_events_today()
    if events:
        for e in events:
            print(f"  {e['start']} – {e['title']}")
    else:
        print("  Heute keine Termine.")


if __name__ == "__main__":
    smoke_test()
