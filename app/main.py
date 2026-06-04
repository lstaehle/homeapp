import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from app.bot import build_application
from app.reminders import daily_reminder, register_jobs
from app.scheduler import get_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_app = build_application()
    await bot_app.initialize()
    await bot_app.start()

    register_jobs(bot_app.bot)
    get_scheduler().start()

    app.state.bot = bot_app.bot

    yield

    get_scheduler().shutdown()
    await bot_app.stop()
    await bot_app.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/test-reminder")
async def test_reminder(request: Request):
    if os.environ.get("ENV") != "dev":
        raise HTTPException(status_code=404, detail="Not found")
    await daily_reminder(request.app.state.bot)
    return {"status": "sent"}


# API routes added in Phase 4 — static mount must come last
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
