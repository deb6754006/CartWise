"""Worker entry point: `python -m app.worker.main`. Runs the scheduled jobs (APScheduler)."""

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import app.modules.registry  # noqa: F401  # loads every module, so their hooks are registered
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.worker.jobs import purge_deleted

PURGE_DELETED_JOB_ID = "purge_deleted"


def schedule_jobs(scheduler: BaseScheduler) -> BaseScheduler:
    """Add every job to scheduler. purge_deleted runs once a day, at 03:00 UTC."""
    scheduler.add_job(
        purge_deleted.run,
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id=PURGE_DELETED_JOB_ID,
        replace_existing=True,
        # A run that starts late (the process was suspended or busy) still runs, once.
        coalesce=True,
        max_instances=1,
        misfire_grace_time=24 * 60 * 60,
    )
    return scheduler


def main() -> None:
    configure_logging(get_settings().LOG_LEVEL)
    scheduler = schedule_jobs(BlockingScheduler(timezone="UTC"))
    scheduler.start()


if __name__ == "__main__":
    main()
