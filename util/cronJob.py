"""
Global cron job scheduler using APScheduler.
Register recurring tasks here; scheduler runs alongside the bot.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from util.logging import log

# Global scheduler instance
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the global scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def start_scheduler() -> None:
    """Start the scheduler if not already running."""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        log.info("Cron scheduler started.")


def stop_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Cron scheduler stopped.")
        _scheduler = None


def add_job(func, trigger, job_id: str, **kwargs) -> None:
    """
    Add a job to the scheduler.
    If a job with the same id exists, it will be replaced.
    """
    scheduler = get_scheduler()
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(func, trigger, id=job_id, **kwargs)
    log.debug(f"Cron job added: {job_id}")


def remove_job(job_id: str) -> None:
    """Remove a job by id if it exists."""
    scheduler = get_scheduler()
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        log.debug(f"Cron job removed: {job_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Pre-defined interval helper
# ─────────────────────────────────────────────────────────────────────────────

def every_minutes(minutes: int):
    """Return an IntervalTrigger for the given minutes."""
    return IntervalTrigger(minutes=minutes)


def every_seconds(seconds: int):
    """Return an IntervalTrigger for the given seconds."""
    return IntervalTrigger(seconds=seconds)
