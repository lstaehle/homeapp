import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.bot import build_application
from app.gcalendar import get_events_today, get_events_this_week
from app.reminders import daily_reminder, register_jobs
from app.scheduler import get_scheduler
from app.todoist import get_restock_items

TZ = ZoneInfo("Europe/Zurich")
GERMAN_DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_app = build_application()
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    register_jobs(bot_app.bot)
    get_scheduler().start()

    app.state.bot = bot_app.bot

    yield

    get_scheduler().shutdown()
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()


app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event_time_str(event: dict) -> str:
    raw = event["start"]
    if "T" in raw:
        return datetime.fromisoformat(raw).astimezone(TZ).strftime("%H:%M")
    return "Ganztägig"


def _event_date_val(event: dict) -> date:
    raw = event["start"]
    if "T" in raw:
        return datetime.fromisoformat(raw).astimezone(TZ).date()
    return date.fromisoformat(raw)


def _week_days() -> list[date]:
    today = datetime.now(TZ).date()
    monday = today - timedelta(days=today.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


# ---------------------------------------------------------------------------
# HTML fragment renderers (returned to htmx requests)
# ---------------------------------------------------------------------------

def _render_today_html(data: dict) -> str:
    lines = [f'<p class="text-gray-400 text-xl mb-4">{data["date"]}</p>']
    if not data["events"]:
        lines.append('<p class="text-2xl text-gray-500">Heute keine Termine.</p>')
    else:
        lines.append('<div class="space-y-4">')
        for e in data["events"]:
            lines.append(f'<div><p class="text-2xl font-medium">• {e["time"]} – {e["title"]}</p>')
            if e["location"]:
                lines.append(f'<p class="text-lg text-gray-400 ml-6">📍 {e["location"]}</p>')
            lines.append("</div>")
        lines.append("</div>")
    return "\n".join(lines)


def _render_week_html(data: dict) -> str:
    lines = []
    for day in data["days"]:
        if not day["events"]:
            continue
        lines.append('<div class="mb-4">')
        lines.append(
            f'<p class="font-semibold text-gray-300 text-xl border-b border-gray-600 pb-1 mb-2">'
            f'{day["weekday"]}, {day["date"]}</p>'
        )
        for e in day["events"]:
            lines.append(f'<p class="text-xl ml-2">• {e["time"]} – {e["title"]}</p>')
        lines.append("</div>")
    if not lines:
        lines.append('<p class="text-xl text-gray-500">Diese Woche keine Termine.</p>')
    return "\n".join(lines)


def _render_grocery_html(items: list[str]) -> str:
    if not items:
        return '<p class="text-xl text-gray-500">Keine Einträge.</p>'
    rows = ["".join(f'<li class="text-xl py-1">• {item}</li>' for item in items)]
    return f'<ul class="space-y-1">{"".join(rows)}</ul>'


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/test-reminder")
async def test_reminder(request: Request):
    if os.environ.get("ENV") != "dev":
        raise HTTPException(status_code=404, detail="Not found")
    await daily_reminder(request.app.state.bot)
    return {"status": "sent"}


# ---------------------------------------------------------------------------
# API endpoints — return JSON by default, HTML fragments for htmx requests
# ---------------------------------------------------------------------------

@app.get("/api/today")
async def api_today(request: Request):
    events = get_events_today()
    data = {
        "date": datetime.now(TZ).strftime("%d.%m.%Y"),
        "events": [
            {"title": e["title"], "time": _event_time_str(e), "location": e["location"]}
            for e in events
        ],
    }
    if request.headers.get("HX-Request"):
        return HTMLResponse(_render_today_html(data))
    return data


@app.get("/api/week")
async def api_week(request: Request):
    events = get_events_this_week()
    days = []
    for day in _week_days():
        day_events = [
            {"title": e["title"], "time": _event_time_str(e), "location": e["location"]}
            for e in events
            if _event_date_val(e) == day
        ]
        days.append({
            "date": day.strftime("%d.%m.%Y"),
            "weekday": GERMAN_DAYS[day.weekday()],
            "events": day_events,
        })
    data = {"days": days}
    if request.headers.get("HX-Request"):
        return HTMLResponse(_render_week_html(data))
    return data


@app.get("/api/grocery")
async def api_grocery(request: Request):
    items = get_restock_items()
    if request.headers.get("HX-Request"):
        return HTMLResponse(_render_grocery_html(items))
    return items


# Static files must be mounted last so API routes take precedence
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
