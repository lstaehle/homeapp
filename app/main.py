from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.scheduler import get_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = get_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


# API routes added in Phase 4 — static mount must come last
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
