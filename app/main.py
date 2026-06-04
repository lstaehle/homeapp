import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

from dotenv import load_dotenv

load_dotenv()

from telegram import Update

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.bot import build_application
from app.gcalendar import get_events_today, get_events_this_week
from app.reminders import daily_reminder, register_jobs
from app.scheduler import get_scheduler
from app.notes import add_note, delete_note, get_notes
from app.todoist import complete_task, get_restock_items
from app.weather import get_weather

TZ = ZoneInfo("Europe/Zurich")
GERMAN_DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


async def _poll_telegram(bot_app) -> None:
    """Manual polling loop running in uvicorn's event loop — avoids PTB/uvicorn asyncio conflicts."""
    await bot_app.bot.delete_webhook()
    offset: int | None = None
    while True:
        try:
            updates = await bot_app.bot.get_updates(
                offset=offset, timeout=10, allowed_updates=Update.ALL_TYPES
            )
            for update in updates:
                offset = update.update_id + 1
                asyncio.create_task(bot_app.process_update(update))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Telegram polling error: %s", exc)
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_app = build_application()
    poll_task = None

    try:
        await bot_app.initialize()
        poll_task = asyncio.create_task(_poll_telegram(bot_app))
        register_jobs(bot_app.bot)
        app.state.bot = bot_app.bot
    except Exception as exc:
        logger.warning("Bot init failed (%s) — running without Telegram", exc)
        app.state.bot = None

    get_scheduler().start()

    yield

    if poll_task:
        poll_task.cancel()
        await asyncio.gather(poll_task, return_exceptions=True)
    get_scheduler().shutdown()
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


def _render_notes_html(notes: list[dict]) -> str:
    if not notes:
        return '<p class="text-lg text-gray-500">Keine Notizen.</p>'
    parts = []
    for note in notes:
        parts.append(
            f'<div id="note-{note["id"]}" class="bg-gray-700 rounded-xl p-3 mb-2">'
            f'<div class="flex justify-between items-start gap-2">'
            f'<p class="text-lg leading-snug flex-1">{note["text"]}</p>'
            f'<button hx-delete="/api/notes/{note["id"]}" hx-target="#note-{note["id"]}" hx-swap="outerHTML"'
            f' class="text-gray-500 hover:text-red-400 text-2xl leading-none flex-shrink-0">×</button>'
            f'</div>'
            f'<p class="text-xs text-gray-500 mt-1">{note["author"]} · {note["created_at"]}</p>'
            f'</div>'
        )
    return "".join(parts)


def _render_grocery_html(groups: list[dict]) -> str:
    if not groups:
        return '<p class="text-xl text-gray-500">Keine Einträge.</p>'
    parts = []
    for group in groups:
        if group["section"]:
            parts.append(
                f'<p class="text-sm font-semibold text-yellow-400 uppercase tracking-wide mt-4 mb-1">'
                f'{group["section"]}</p>'
            )
        for item in group["items"]:
            parts.append(
                f'<li id="grocery-{item["id"]}" class="flex items-center gap-3 py-1">'
                f'<button'
                f' hx-post="/api/grocery/{item["id"]}/complete"'
                f' hx-target="closest li"'
                f' hx-swap="outerHTML"'
                f' class="w-8 h-8 rounded border-2 border-gray-500 flex-shrink-0'
                f' hover:border-green-400 hover:bg-green-400/20 active:bg-green-400/40 transition-colors">'
                f'</button>'
                f'<span class="text-xl">{item["content"]}</span>'
                f'</li>'
            )
    return f'<ul class="space-y-0">{"".join(parts)}</ul>'


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------

@app.get("/api/weather")
async def api_weather(request: Request):
    try:
        w = get_weather()
    except Exception as exc:
        logger.error("get_weather failed: %s", exc)
        w = None
    if not request.headers.get("HX-Request"):
        return w or {}
    if not w:
        return HTMLResponse("")
    return HTMLResponse(
        f'<p class="text-xl text-gray-300 mb-3">'
        f'{w["emoji"]} {w["temp"]}°C &nbsp;·&nbsp; {w["description"]} &nbsp;·&nbsp; '
        f'<span class="text-gray-500">gefühlt {w["feels_like"]}°C</span>'
        f'</p>'
    )


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
    try:
        events = get_events_today()
    except Exception as exc:
        logger.error("get_events_today failed: %s", exc)
        events = []
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
    try:
        events = get_events_this_week()
    except Exception as exc:
        logger.error("get_events_this_week failed: %s", exc)
        events = []
    today = datetime.now(TZ).date()
    days = []
    for day in _week_days():
        if day <= today:
            continue
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
    try:
        items = get_restock_items()
    except Exception as exc:
        logger.error("get_restock_items failed: %s", exc)
        items = []
    if request.headers.get("HX-Request"):
        return HTMLResponse(_render_grocery_html(items))
    return items


@app.get("/api/notes")
async def api_notes(request: Request):
    notes = get_notes()
    if request.headers.get("HX-Request"):
        return HTMLResponse(_render_notes_html(notes))
    return notes


@app.delete("/api/notes/{note_id}")
async def api_delete_note(note_id: str):
    delete_note(note_id)
    return HTMLResponse("")


@app.post("/api/grocery/{task_id}/complete")
async def complete_grocery(task_id: str):
    try:
        complete_task(task_id)
    except Exception as exc:
        logger.error("complete_task failed: %s", exc)
    return HTMLResponse("")


# Static files must be mounted last so API routes take precedence
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
