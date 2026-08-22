# Home Family App

## Overview
A family coordination app for two adults and two kids (ages 7 and 5), self-hosted on a Raspberry Pi Zero 2W. All UI and messages are in German.

**Two main surfaces:**
- **Kitchen tablet dashboard** — full-screen, dark-mode, 4-panel layout; auto-refreshes via htmx polling
- **Telegram bot** — event creation, notes, and daily/weekly reminders

---

## Features

### Dashboard panels
| Panel | Content | Refresh |
|---|---|---|
| 📅 Heute | Weather widget (current temp, feels like, daily max) + today's Google Calendar events | every 300s |
| 🗓 Diese Woche | Google Calendar events from tomorrow through end of week | every 300s |
| 🛒 Einkauf | Todoist grocery list grouped by section; tap checkbox to complete item in Todoist | every 300s |
| 📌 Notizen | Notes added via Telegram `/note`; tap × to delete | every 30s |

### Telegram bot commands
| Command | Function |
|---|---|
| `/event` | Start guided event creation (date + optional title in one message; asks for year only if `TT.MM.JJJJ` given) |
| `/skip` | Skip optional description step during event creation |
| `/abbrechen` | Cancel event creation at any step |
| `/note <text>` | Save a note visible on the dashboard |
| `/ping` | Liveness check |
| `/sex TT.MM HH:MM [style]` or `/sex <text>` | Propose private time together; save to cycle calendar after Ja/vielleicht |
| `/period [TT.MM]` | Save cycle start in the separate cycle calendar |
| `/periodhistory` | Show recorded cycle starts and intervals |
| `/periodnext` | Predict next cycle start and save expected event |

### Scheduled reminders (Europe/Zurich)
- **06:00 daily** — today's events sent to both Telegram chat IDs
- **Monday 06:00** — full week events sent to both Telegram chat IDs

---

## Tech Stack

### Backend
| Component | Choice | Notes |
|---|---|---|
| Language | Python 3.12 | |
| HTTP framework | FastAPI + uvicorn | Route handlers are `def` (not `async def`) so blocking I/O runs in FastAPI's thread pool and panels load in parallel |
| Scheduler | APScheduler 3.10 AsyncIOScheduler | Daily + weekly reminders |
| Telegram | python-telegram-bot v21.6 | Manual asyncio polling loop (avoids PTB/uvicorn event loop conflicts) |
| Google Calendar | google-api-python-client + google-auth | OAuth2; `token.json` mounted writable so refresh tokens persist |
| Todoist | Direct httpx to API v1 (`https://api.todoist.com/api/v1`) | Official SDK dropped (used deprecated REST v2 / 410 Gone); API v1 responses wrapped in `{"results": [...]}` |
| Weather | Open-Meteo (`http://`, not `https://`) | HTTP used to avoid SSL handshake timeout on Pi Zero 2W; WMO weather codes mapped to German descriptions + emoji; daily max temp included |
| Notes | JSON file at `data/notes.json` | Persisted via Docker volume |
| Config | python-dotenv + `.env` | |

### Frontend
| Component | Choice |
|---|---|
| Interactivity | htmx 1.9.12 (panel polling) + Alpine.js 3.14 (clock) |
| Styling | Tailwind CSS (CDN) |
| Served by | FastAPI static mount |

### Infrastructure
| Component | Choice |
|---|---|
| Runtime | Raspberry Pi Zero 2W (`lorenzpi@lorenzpi.local`) |
| Containerisation | Docker Compose, `restart: unless-stopped` |
| DNS | Explicit `8.8.8.8` + `1.1.1.1` in `docker-compose.yml` (Pi-hole on Synology NAS at `192.168.178.86` can go down) |
| Port | 8000 |

---

## Environment Variables

```
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID_1
TELEGRAM_CHAT_ID_2
GOOGLE_CREDENTIALS_FILE   # path to credentials.json
GOOGLE_TOKEN_FILE         # path to token.json (writable)
GOOGLE_CALENDAR_ID        # staehlefamily89@gmail.com
CYCLE_GOOGLE_CALENDAR_ID  # separate Google Calendar for cycle tracking
TODOIST_API_TOKEN
TODOIST_PROJECT_NAME      # e.g. Groceries
WEATHER_LAT               # e.g. 46.70306
WEATHER_LON               # e.g. 9.4085
WEATHER_ELEVATION         # metres above sea level, e.g. 690 (Flerden)
ENV                       # set to "dev" to enable /test-reminder endpoint
```

---

## Deployment

```bash
# First deploy / after code change
cd ~/homeapp
git pull
docker compose up -d --build

# Restart only (e.g. after .env change)
docker compose restart

# Logs
docker compose logs -f
```

Docker volumes (defined in `docker-compose.yml`):
```yaml
volumes:
  - ./.env:/app/.env:ro
  - ./credentials.json:/app/credentials.json:ro
  - ./token.json:/app/token.json      # writable — Google refreshes the token
  - ./data:/app/data                  # notes.json persisted here
```

---

## Key Decisions & Lessons Learned

| Topic | Decision / Fix |
|---|---|
| Todoist SDK | Replaced `todoist-api-python` (REST v2, 410 Gone) with direct httpx to API v1 |
| Weather provider | Switched from OpenWeatherMap to Open-Meteo for accuracy; HTTP (not HTTPS) to avoid SSL timeout on Pi Zero 2W |
| Weather accuracy | Added `WEATHER_ELEVATION` parameter; corrected coordinates to exact village location (Flerden: `46.70306, 9.4085`, 690m) |
| Async / blocking I/O | All data-fetching FastAPI routes are `def` (not `async def`) — FastAPI runs them in a thread pool so all panels load in parallel |
| Telegram polling | Manual `asyncio` polling loop replaces PTB's built-in `Updater` to share uvicorn's event loop without conflicts |
| Docker DNS | Pi-hole on Synology NAS is a single point of failure; added Google/Cloudflare DNS as fallback in `docker-compose.yml` |
| token.json | Must be mounted writable (not `:ro`) — Google auth rewrites the file on token refresh |
| Calendar | Migrated from Proton Calendar to Google Calendar (`staehlefamily89@gmail.com`) |
| Week panel | Shows tomorrow onwards only — today is already covered by the Heute panel |
| Notes refresh | Polls every 30s (not 300s) so Telegram notes appear on the dashboard quickly |
