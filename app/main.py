import asyncio
import json
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
from pydantic import BaseModel

from app.bot import build_application
from app.gcalendar import get_events_today, get_events_this_week, get_events_range
from app.reminders import daily_reminder, register_jobs
from app.scheduler import get_scheduler
from app.notes import add_note, delete_note, get_notes
from app.todoist import complete_task, create_task, get_restock_items
from app.weather import get_weather, get_forecast
from app.meals import (
    get_plan, set_meal, delete_meal,
    get_meal_list, get_meal_names, add_to_meal_list, set_meal_ingredients,
    get_pending_ingredients, mark_ingredients_sent,
)


class MealBody(BaseModel):
    meal: str

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
    date_iso = data["date_iso"]
    meal = data.get("meal")
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
    lines.append('<div class="mt-4 pt-3 border-t border-gray-700">')
    if meal:
        lines.append(
            f'<div class="flex items-center gap-2">'
            f'<span class="text-xl text-orange-200">🍽 {meal}</span>'
            f'<button onclick="Alpine.store(\'meal\').remove(\'{date_iso}\')"'
            f' class="text-gray-600 hover:text-red-400 text-xl leading-none">×</button>'
            f'</div>'
        )
    else:
        lines.append(
            f'<button onclick="Alpine.store(\'meal\').openFor(\'{date_iso}\')"'
            f' class="text-gray-500 hover:text-green-400 text-base transition-colors">🍽 + Mahlzeit</button>'
        )
    lines.append('</div>')
    return "\n".join(lines)


def _render_week_html(data: dict) -> str:
    if not data["days"]:
        return '<p class="text-xl text-gray-500">Keine Vorschau verfügbar.</p>'
    lines = []
    for day in data["days"]:
        w = day.get("weather")
        weather_str = (
            f' &nbsp;·&nbsp; {w["emoji"]} {w["temp_min"]}–{w["temp_max"]}°C'
            if w else ""
        )
        date_iso = day["date_iso"]
        meal = day.get("meal")
        lines.append('<div class="mb-3">')
        lines.append(
            f'<p class="font-semibold text-gray-300 text-lg border-b border-gray-600 pb-1 mb-1">'
            f'{day["weekday"]}, {day["date"]}{weather_str}</p>'
        )
        for e in day["events"]:
            lines.append(f'<p class="text-lg ml-2">• {e["time"]} – {e["title"]}</p>')
        if meal:
            lines.append(
                f'<div class="flex items-center gap-2 mt-1">'
                f'<span class="text-base text-orange-200">🍽 {meal}</span>'
                f'<button onclick="Alpine.store(\'meal\').remove(\'{date_iso}\')"'
                f' class="text-gray-600 hover:text-red-400 text-lg leading-none ml-1">×</button>'
                f'</div>'
            )
        else:
            lines.append(
                f'<button onclick="Alpine.store(\'meal\').openFor(\'{date_iso}\')"'
                f' class="mt-1 text-gray-500 hover:text-green-400 text-sm transition-colors">+ Mahlzeit</button>'
            )
        lines.append("</div>")
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


def _render_grocery_html(groups: list[dict], pending: list[dict] | None = None) -> str:
    parts = []

    if pending:
        parts.append('<div class="mb-3">')
        parts.append(
            '<p class="text-sm font-semibold text-purple-400 uppercase tracking-wide mb-2">⏳ Ausstehend</p>'
        )
        for p in pending:
            parts.append(
                f'<div class="mb-3 bg-gray-700/50 rounded-xl p-3">'
                f'<p class="text-sm text-gray-400 mb-1">{p["label"]} — {p["meal"]}</p>'
                f'<ul class="mb-2 space-y-0.5">'
            )
            for ing in p["ingredients"]:
                parts.append(f'<li class="text-base text-gray-200">• {ing}</li>')
            parts.append(
                f'</ul>'
                f'<button'
                f' hx-post="/api/grocery/pending/{p["date"]}/confirm"'
                f' hx-target="#panel-einkauf"'
                f' hx-swap="innerHTML"'
                f' hx-headers=\'{{"HX-Request": "true"}}\''
                f' class="text-sm text-purple-400 hover:text-purple-200 transition-colors">'
                f'+ Zur Einkaufsliste hinzufügen'
                f'</button>'
                f'</div>'
            )
        parts.append('</div>')
        if groups:
            parts.append('<hr class="border-gray-700 mb-3">')

    if not groups and not pending:
        return '<p class="text-xl text-gray-500">Keine Einträge.</p>'

    todoist_parts = []
    for group in groups:
        if group["section"]:
            todoist_parts.append(
                f'<p class="text-sm font-semibold text-yellow-400 uppercase tracking-wide mt-4 mb-1">'
                f'{group["section"]}</p>'
            )
        for item in group["items"]:
            todoist_parts.append(
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
    if todoist_parts:
        parts.append(f'<ul class="space-y-0">{"".join(todoist_parts)}</ul>')

    return "".join(parts)


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------

@app.get("/api/weather")
def api_weather(request: Request):
    try:
        w = get_weather()
    except Exception as exc:
        logger.error("get_weather failed: %s", exc)
        w = None
    if not request.headers.get("HX-Request"):
        return w or {}
    if not w:
        return HTMLResponse('<p class="text-xl text-gray-500">Wetter nicht verfügbar.</p>')
    return HTMLResponse(
        f'<p class="text-xl text-gray-300 mb-3">'
        f'{w["emoji"]} {w["temp"]}°C &nbsp;·&nbsp; {w["description"]} &nbsp;·&nbsp; '
        f'<span class="text-gray-500">gefühlt {w["feels_like"]}°C</span>'
        f'&nbsp;·&nbsp; <span class="text-orange-300">max {w["temp_max"]}°C</span>'
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
def api_today(request: Request):
    today = datetime.now(TZ).date()
    try:
        events = get_events_today()
    except Exception as exc:
        logger.error("get_events_today failed: %s", exc)
        events = []
    try:
        meal = get_plan().get(today.isoformat())
    except Exception as exc:
        logger.error("get_plan failed: %s", exc)
        meal = None
    data = {
        "date": datetime.now(TZ).strftime("%d.%m.%Y"),
        "date_iso": today.isoformat(),
        "meal": meal,
        "events": [
            {"title": e["title"], "time": _event_time_str(e), "location": e["location"]}
            for e in events
        ],
    }
    if request.headers.get("HX-Request"):
        return HTMLResponse(_render_today_html(data))
    return data


@app.get("/api/week")
def api_week(request: Request):
    today = datetime.now(TZ).date()
    tomorrow = today + timedelta(days=1)
    end = today + timedelta(days=5)

    try:
        forecast = {f["date"]: f for f in get_forecast(days=5)}
    except Exception as exc:
        logger.error("get_forecast failed: %s", exc)
        forecast = {}

    try:
        start_dt = datetime.combine(tomorrow, datetime.min.time()).replace(tzinfo=TZ)
        end_dt = datetime.combine(end, datetime.max.time().replace(microsecond=0)).replace(tzinfo=TZ)
        events = get_events_range(start_dt, end_dt)
    except Exception as exc:
        logger.error("get_events_range failed: %s", exc)
        events = []

    try:
        meal_plan = get_plan()
        meal_list = get_meal_list()
    except Exception as exc:
        logger.error("get meals failed: %s", exc)
        meal_plan = {}
        meal_list = []

    days = []
    for i in range(5):
        day = tomorrow + timedelta(days=i)
        day_str = day.isoformat()
        day_events = [
            {"title": e["title"], "time": _event_time_str(e), "location": e["location"]}
            for e in events
            if _event_date_val(e) == day
        ]
        days.append({
            "date": day.strftime("%d.%m."),
            "date_iso": day_str,
            "weekday": GERMAN_DAYS[day.weekday()],
            "weather": forecast.get(day_str),
            "events": day_events,
            "meal": meal_plan.get(day_str),
        })

    data = {"days": days, "meal_list": meal_list}
    if request.headers.get("HX-Request"):
        return HTMLResponse(_render_week_html(data))
    return data


@app.get("/api/grocery")
def api_grocery(request: Request):
    try:
        items = get_restock_items()
    except Exception as exc:
        logger.error("get_restock_items failed: %s", exc)
        items = []
    try:
        pending = get_pending_ingredients()
    except Exception as exc:
        logger.error("get_pending_ingredients failed: %s", exc)
        pending = []
    if request.headers.get("HX-Request"):
        return HTMLResponse(_render_grocery_html(items, pending))
    return {"items": items, "pending": pending}


@app.get("/api/notes")
def api_notes(request: Request):
    notes = get_notes()
    if request.headers.get("HX-Request"):
        return HTMLResponse(_render_notes_html(notes))
    return notes


@app.delete("/api/notes/{note_id}")
def api_delete_note(note_id: str):
    delete_note(note_id)
    return HTMLResponse("")


@app.post("/api/grocery/{task_id}/complete")
def complete_grocery(task_id: str):
    try:
        complete_task(task_id)
    except Exception as exc:
        logger.error("complete_task failed: %s", exc)
    return HTMLResponse("")


@app.get("/api/meals")
def api_meals():
    return {"plan": get_plan(), "list": get_meal_list()}


@app.get("/api/meals/config")
def api_meals_config():
    return get_meal_list()


class IngredientsBody(BaseModel):
    ingredients: list[str]


@app.put("/api/meals/config/{meal_name}")
def api_set_meal_ingredients(meal_name: str, body: IngredientsBody):
    set_meal_ingredients(meal_name, body.ingredients)
    return {"ok": True}


@app.post("/api/grocery/pending/{day}/confirm")
def api_confirm_pending(day: str, request: Request):
    pending = get_pending_ingredients()
    for p in pending:
        if p["date"] == day:
            for ingredient in p["ingredients"]:
                try:
                    create_task(ingredient)
                except Exception as exc:
                    logger.error("create_task failed for %r: %s", ingredient, exc)
            mark_ingredients_sent(day)
            break
    try:
        items = get_restock_items()
    except Exception as exc:
        logger.error("get_restock_items failed: %s", exc)
        items = []
    remaining_pending = get_pending_ingredients()
    if request.headers.get("HX-Request"):
        return HTMLResponse(_render_grocery_html(items, remaining_pending))
    return {"ok": True}


@app.post("/api/meals/plan/{day}")
def api_set_meal(day: str, body: MealBody):
    set_meal(date.fromisoformat(day), body.meal)
    return {"ok": True}


@app.delete("/api/meals/plan/{day}")
def api_delete_meal(day: str):
    delete_meal(date.fromisoformat(day))
    return {"ok": True}


@app.post("/api/meals/list")
def api_add_meal_to_list(body: MealBody):
    add_to_meal_list(body.meal)
    return {"ok": True}


# Static files must be mounted last so API routes take precedence
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
