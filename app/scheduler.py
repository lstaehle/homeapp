from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TZ = ZoneInfo("Europe/Zurich")

scheduler = AsyncIOScheduler(timezone=TZ)


def get_scheduler() -> AsyncIOScheduler:
    return scheduler
