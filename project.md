# Home Family App

## Overview
A family coordination app for two adults and two kids (ages 7 and 5) with:
- Calendar reminders via Telegram (daily 6am + Monday weekly digest)
- Telegram bot to create new calendar events
- Kitchen tablet dashboard (today's events, week outlook, grocery list)
- Todoist integration for grocery/restocking list

---

## Tech Stack

### Backend (Python monolith — keeps ops simple on a home server)
| Component | Choice | Reason |
|---|---|---|
| Language | Python 3.12 | Best ecosystem for all three APIs (Calendar, Telegram, Todoist) |
| HTTP framework | FastAPI | Serves the kitchen dashboard API; async-native |
| Scheduler | APScheduler | In-process cron for 6am daily + Monday reminders |
| Telegram bot | python-telegram-bot v21 | Mature, async, conversation-handler support for guided event creation |
| Google Calendar | google-api-python-client + google-auth | Official SDK |
| Todoist | todoist-api-python | Official SDK |
| Config/secrets | python-dotenv + .env file | Simple secret management |

### Kitchen Display (Frontend)
| Component | Choice | Reason |
|---|---|---|
| Framework | Plain HTML + Alpine.js + htmx | No build step, runs in any tablet browser, auto-refresh via htmx polling |
| Styling | Tailwind CSS (CDN) | Clean dashboard look, no build tooling needed |
| Served by | FastAPI static mount | Single process, no separate web server |

### Infrastructure
| Component | Choice | Reason |
|---|---|---|
| Containerisation | Docker Compose | One command to start everything; easy to update |
| Runtime target | Raspberry Pi 4 / home server | Self-hosted, no cloud costs |
| Process management | Docker restart policy | Auto-restart on reboot |
| Reverse proxy | Caddy (optional) | Simple HTTPS if exposed beyond LAN |

---

## Implementation Plan

### Pre-flight — GitHub Repo (manual, ~5 min)
1. Run `gh repo create homeapp --private --clone` (or create via github.com)
2. Copy your Google Calendar credentials JSON into the repo root as `credentials.json` (already gitignored)
3. Fill in `.env` from `.env.example` once Phase 1 generates it

---

### Phase 1 — Project Skeleton & API Credentials (~35 min total)

**Manual steps first:**
- Google Cloud Console: create project → enable Calendar API → create OAuth 2.0 Desktop credentials → download JSON (~15 min)
- Telegram: message @BotFather → `/newbot` → copy token (~5 min)
- Todoist: Settings → Integrations → API token; create "Einkauf" project (~5 min)

**Claude Code prompt:**
```
Scaffold a Python family home app in this directory. Structure:
  app/
    main.py          # FastAPI app entry point
    calendar.py      # Google Calendar API helpers
    todoist.py       # Todoist API helpers
    bot.py           # Telegram bot setup
    reminders.py     # APScheduler jobs
    scheduler.py     # Scheduler init
  frontend/
    index.html       # Kitchen dashboard
  .env.example       # All required env vars with comments
  .gitignore         # Ignore .env, credentials.json, __pycache__, .venv
  requirements.txt   # All dependencies pinned

Dependencies: fastapi, uvicorn, python-telegram-bot==21.*, apscheduler, 
google-api-python-client, google-auth-httplib2, google-auth-oauthlib, 
todoist-api-python, python-dotenv, httpx

.env.example must include: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID_1, 
TELEGRAM_CHAT_ID_2, GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, 
TODOIST_API_TOKEN, TODOIST_PROJECT_NAME

In calendar.py write a get_events_today() and get_events_this_week() function 
that authenticates via OAuth and returns a list of event dicts with keys: 
title, start, end, location.

Add a smoke_test() in calendar.py that prints today's events when run directly.

Commit everything and push to origin main.
```

**Test prompt:**
```
Add a test suite for Phase 1. Use pytest with pytest-mock. Add pytest, pytest-mock, 
pytest-asyncio, and respx to requirements.txt (dev section).

tests/unit/test_calendar.py:
- test_get_events_today_returns_list: patch googleapiclient.discovery.build; 
  mock API returning two events; assert result is a list of dicts each with 
  keys {title, start, end, location}
- test_get_events_today_empty: mock API returning no items; assert returns []
- test_get_events_this_week_time_range: capture the timeMin/timeMax passed to 
  the API; assert timeMin is Monday 00:00 and timeMax is Sunday 23:59 of the 
  current week (Europe/Zurich)
- test_event_with_missing_location: event without location field returns 
  location as empty string, not KeyError

tests/unit/test_todoist.py:
- test_get_restock_items_returns_task_names: mock todoist_api_python.TodoistAPI; 
  assert get_restock_items() returns list of task content strings for the 
  configured project
- test_get_restock_items_filters_by_project: tasks from other projects are 
  excluded from result
- test_get_restock_items_empty: returns [] when no open tasks exist

tests/unit/test_config.py:
- test_env_example_contains_all_vars: parse .env.example and assert all 7 
  required variable names are present
- test_gitignore_excludes_secrets: read .gitignore and assert it contains 
  ".env", "credentials.json", "token.json"

Run: pytest tests/unit/ -v
Commit and push to origin main.
```

---

### Phase 2 — Telegram Reminders (~15 min)

**Claude Code prompt:**
```
In reminders.py implement two APScheduler jobs using AsyncIOScheduler:

1. daily_reminder() — fires every day at 06:00 Europe/Zurich:
   - Calls get_events_today() from calendar.py
   - Formats a German message: "Guten Morgen! 🗓 Heute, {Datum}:\n" 
     followed by each event as "• {Uhrzeit} – {Titel}" 
     or "Heute keine Termine." if empty
   - Sends to TELEGRAM_CHAT_ID_1 and TELEGRAM_CHAT_ID_2

2. weekly_reminder() — fires every Monday at 06:00 Europe/Zurich:
   - Calls get_events_this_week() from calendar.py
   - Formats a German message: "Gute Woche! 📅 Diese Woche:\n"
     grouped by day, each day as a header "**{Wochentag}, {Datum}**"
     followed by events, or "Diese Woche keine Termine." if empty
   - Sends to both chat IDs

Wire the scheduler into main.py so it starts with the FastAPI app (lifespan event).
Add a /test-reminder endpoint (dev only, guarded by ENV=dev) that fires daily_reminder() immediately for testing.

Commit and push to origin main.
```

**Test prompt:**
```
Add tests for Phase 2 in tests/unit/test_reminders.py. All formatting logic 
must be extracted into pure functions (format_daily_message(events, date) and 
format_weekly_message(events_by_day)) so they can be tested without touching 
the Telegram API or scheduler.

test_reminders.py:
- test_daily_message_with_events: given two events, output starts with 
  "Guten Morgen!" and contains both event titles and their times
- test_daily_message_empty: output contains "Heute keine Termine."
- test_daily_message_contains_formatted_date: German date format (e.g. 
  "Montag, 03.06.2026") appears in message
- test_weekly_message_with_events: output starts with "Gute Woche!" and 
  events are grouped under their respective day headers
- test_weekly_message_empty: output contains "Diese Woche keine Termine."
- test_weekly_message_day_headers_in_german: day headers use German weekday 
  names (Montag, Dienstag, etc.)
- test_weekly_message_multiple_days: events on three different days each 
  appear under a separate header

Run: pytest tests/unit/test_reminders.py -v
Commit and push to origin main.
```

---

### Phase 3 — Telegram Event Creation (~20 min)

**Claude Code prompt:**
```
In bot.py implement a Telegram ConversationHandler for the command /neuesevent.

Flow (all prompts in German):
1. Ask: "Wie soll der Termin heißen?"  → save title
2. Ask: "An welchem Datum? (Format: TT.MM.JJJJ)"  → validate, re-ask on invalid
3. Ask: "Um wie viel Uhr? (Format: HH:MM)"  → validate, re-ask on invalid
4. Ask: "Wie lange dauert der Termin? (z.B. 1h, 90min, oder 'ganzer Tag')"
5. Ask: "Optionale Beschreibung? (oder /überspringen)"
6. Show summary and ask: "Termin speichern? (Ja / Nein)"
   - Ja → call create_event() in calendar.py → confirm "✅ Termin gespeichert!"
   - Nein → "❌ Abgebrochen."
   - /abbrechen at any step → cancel

Implement create_event(title, start_dt, end_dt, description) in calendar.py 
using the Calendar API.

Register the ConversationHandler in main.py when the bot application starts 
(use ApplicationBuilder, run alongside uvicorn via asyncio).

Commit and push to origin main.
```

**Test prompt:**
```
Add tests for Phase 3.

tests/unit/test_bot_validation.py — test pure validation/parsing helpers 
extracted from bot.py:
- test_parse_date_valid: "25.12.2026" → datetime.date(2026, 12, 25)
- test_parse_date_invalid_format: "2026-12-25" raises ValueError
- test_parse_date_out_of_range: "32.13.2026" raises ValueError
- test_parse_time_valid: "14:30" → datetime.time(14, 30)
- test_parse_time_invalid: "25:00", "abc", "" each raise ValueError
- test_parse_duration_hours: "1h" → timedelta(hours=1)
- test_parse_duration_minutes: "90min" → timedelta(minutes=90)
- test_parse_duration_full_day: "ganzer Tag" → returns all_day=True flag
- test_parse_duration_invalid: "morgen" raises ValueError

tests/integration/test_bot_conversation.py — use python-telegram-bot's 
PTBApplicationBuilder in test mode with a mocked Bot:
- test_neuesevent_happy_path: simulate full conversation 
  (title → date → time → duration → description → "Ja"); assert 
  create_event() is called once with correct title, start_dt, end_dt
- test_neuesevent_cancel_mid_flow: send /abbrechen after date step; 
  assert create_event() is never called and conversation ends
- test_neuesevent_invalid_date_retry: send invalid date, then valid date; 
  assert bot re-asked the date question and eventually continues
- test_neuesevent_nein_confirmation: complete flow but answer "Nein"; 
  assert create_event() not called and "Abgebrochen" in response

Run: pytest tests/unit/test_bot_validation.py tests/integration/test_bot_conversation.py -v
Commit and push to origin main.
```

---

### Phase 4 — Kitchen Dashboard (~25 min)

**Claude Code prompt:**
```
Build the kitchen tablet dashboard.

Backend — add to main.py:
  GET /api/today   → returns {date, events: [{title, time, location}]}
  GET /api/week    → returns {days: [{date, weekday, events: [...]}]}
  GET /api/grocery → calls todoist.py get_restock_items() which returns all 
                     open tasks in the project named TODOIST_PROJECT_NAME

Mount frontend/ as static files at /.

Frontend — frontend/index.html:
- Full-screen layout, dark background, white text, no scrollbars
- Three panels side by side:
    Left (40%): "Heute" — today's events, large font (min 1.5rem)
    Center (40%): "Diese Woche" — week events grouped by day
    Right (20%): "Einkauf" — grocery items as a simple list
- Uses htmx to poll /api/today, /api/week, /api/grocery every 5 minutes 
  and replace panel content in-place (no full reload)
- Tailwind CSS via CDN, Alpine.js via CDN for minor interactivity
- Shows last-updated timestamp in small text at bottom
- Designed for a 10" tablet in landscape, readable from 1m distance

Commit and push to origin main.
```

**Test prompt:**
```
Add tests for Phase 4 using FastAPI's TestClient (sync) and httpx.AsyncClient 
(async). Mock app/calendar.py and app/todoist.py at the module level so no 
real API calls are made.

tests/unit/test_api.py:
- test_today_endpoint_structure: GET /api/today returns JSON with keys 
  "date" (string) and "events" (list)
- test_today_endpoint_event_fields: each event in the list has "title", 
  "time", "location"
- test_today_endpoint_empty_calendar: when get_events_today() returns [], 
  response is {date: ..., events: []}
- test_week_endpoint_structure: GET /api/week returns JSON with key "days" 
  (list of objects with "date", "weekday", "events")
- test_week_endpoint_has_seven_days: "days" list always has exactly 7 entries 
  (days with no events appear with events: [])
- test_grocery_endpoint_returns_list: GET /api/grocery returns a JSON array
- test_grocery_endpoint_empty: when get_restock_items() returns [], 
  response is []
- test_grocery_endpoint_item_format: each item is a string (task content)

tests/unit/test_dashboard.py:
- test_dashboard_serves_html: GET / returns 200 with Content-Type text/html
- test_dashboard_contains_panel_ids: response body contains the strings 
  "panel-heute", "panel-woche", "panel-einkauf"
- test_dashboard_contains_htmx: response body contains "hx-get" (htmx polling)

Run: pytest tests/unit/test_api.py tests/unit/test_dashboard.py -v
Commit and push to origin main.
```

---

### Phase 5 — Docker & Polish (~15 min)

**Claude Code prompt:**
```
Containerise and polish the app.

1. Dockerfile (multi-stage, python:3.12-slim):
   - Install dependencies from requirements.txt
   - Copy app/ and frontend/
   - Expose port 8000
   - Entrypoint: uvicorn app.main:app --host 0.0.0.0 --port 8000

2. docker-compose.yml:
   - Service: homeapp, build: ., restart: unless-stopped
   - Volumes: mount .env and credentials.json and token.json read-only
   - Port: 8000:8000

3. Error notifications: wrap each APScheduler job in a try/except; on exception 
   send a German error message to TELEGRAM_CHAT_ID_1: 
   "⚠️ Homeapp Fehler in {job_name}: {error}"

4. README.md with setup steps:
   - Prerequisites (Docker, gh CLI, Google Cloud, BotFather, Todoist)
   - How to get credentials for each service
   - How to find your Telegram chat ID
   - How to run: docker compose up -d
   - How to deploy on Raspberry Pi

Commit and push to origin main.
```

**Test prompt:**
```
Add a system test suite and finalize the full test run.

tests/system/test_docker.py — requires Docker and docker compose installed; 
uses subprocess to bring the stack up with a test .env (no real credentials, 
ENV=dev):
- test_container_builds: `docker compose build` exits with code 0
- test_container_starts: `docker compose up -d` succeeds and container 
  reaches healthy/running state within 15 seconds
- test_health_endpoint: GET http://localhost:8000/health returns 200 
  (add a /health endpoint to main.py that returns {"status": "ok"})
- test_dashboard_loads: GET http://localhost:8000/ returns 200 and 
  Content-Type text/html
- test_api_endpoints_reachable: /api/today, /api/week, /api/grocery all 
  return 200 (mocked credentials return empty data, not errors)
- teardown: `docker compose down` after all tests

tests/unit/test_error_notifications.py:
- test_job_exception_sends_telegram: patch the Telegram bot send_message; 
  simulate a job raising an exception; assert send_message was called with 
  a message containing "⚠️ Homeapp Fehler"
- test_error_message_contains_job_name: the error notification includes the 
  name of the failed job

Add a CI-friendly test script to package.json or a Makefile:
  make test-unit   → pytest tests/unit/ -v
  make test-system → pytest tests/system/ -v (requires Docker)
  make test        → runs both in sequence

Run: make test-unit
Commit and push to origin main.
```

---

**Total: ~2–2.5 hours** (dominated by manual credential setup, not coding)

---

## Decisions

| Topic | Decision |
|---|---|
| Calendar | **Full migration** from Proton Calendar to Google Calendar; use Google Calendar API |
| Todoist convention | **Create** a new "Einkauf" project; all open tasks = needs restocking |
| Telegram recipients | Both adults; wife will create a Telegram account — two TELEGRAM_CHAT_IDs |
| Infrastructure | **Raspberry Pi** (home server), Docker Compose; kitchen tablet OS not yet decided — kiosk setup deferred to Phase 5 |
| Language | **German** — all bot messages, prompts, and dashboard labels |
