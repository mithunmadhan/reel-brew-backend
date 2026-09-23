import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.database import SessionLocal
from app.services.account_sync import sync_all_active_accounts

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def run_sync_job() -> dict:
    """Wrapper the scheduler calls directly: owns its own DB session since there's no
    per-request session to reuse in a background job.
    """
    db = SessionLocal()
    try:
        return await sync_all_active_accounts(db)
    finally:
        db.close()


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        run_sync_job,
        trigger=IntervalTrigger(hours=4),
        id="sync_all_active_accounts",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: sync_all_active_accounts will run every 4 hours")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
