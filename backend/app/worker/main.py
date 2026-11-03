"""Worker entry point: `python -m app.worker.main`. Runs the scheduled jobs (APScheduler)."""

from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import app.modules.registry  # noqa: F401  # loads every module, so their hooks are registered
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.modules.ingestion.adapters import CHAIN_KEYS
from app.worker.jobs import ingest_chain, purge_deleted

PURGE_DELETED_JOB_ID = "purge_deleted"
INGEST_JOB_IDS = tuple(f"ingest_{key}" for key in CHAIN_KEYS)


def schedule_jobs(scheduler: BaseScheduler) -> BaseScheduler:
    """Add every job to scheduler. purge_deleted runs once a day, at 03:00 UTC. Each chain is
    ingested every INGEST_INTERVAL_HOURS (at most 6), the first time a few minutes after start."""
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
    hours = get_settings().INGEST_INTERVAL_HOURS
    started = datetime.now(UTC)
    for i, (key, job_id) in enumerate(zip(CHAIN_KEYS, INGEST_JOB_IDS, strict=True)):
        scheduler.add_job(
            ingest_chain.run,
            IntervalTrigger(hours=hours, timezone="UTC"),
            args=[key],
            id=job_id,
            replace_existing=True,
            # After a restart the chains are not left waiting a whole interval; staggered, so
            # the three downloads do not start together.
            next_run_time=started + timedelta(minutes=2 + 5 * i),
            coalesce=True,
            max_instances=1,
            misfire_grace_time=hours * 60 * 60,
        )
    return scheduler


def main() -> None:
    configure_logging(get_settings().LOG_LEVEL)
    scheduler = schedule_jobs(BlockingScheduler(timezone="UTC"))
    scheduler.start()


if __name__ == "__main__":
    main()
