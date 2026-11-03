"""The worker schedules purge_deleted once a day (Story 1.7). No database, no running loop."""

from datetime import UTC, datetime, timedelta

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app.worker import main as worker
from app.worker.jobs import purge_deleted


def test_purge_deleted_is_scheduled_once_a_day() -> None:
    scheduler = worker.schedule_jobs(BackgroundScheduler(timezone="UTC"))
    jobs = scheduler.get_jobs()
    assert [job.id for job in jobs] == [worker.PURGE_DELETED_JOB_ID]
    job = jobs[0]
    assert job.func is purge_deleted.run
    assert job.max_instances == 1

    start = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    first = job.trigger.get_next_fire_time(None, start)
    second = job.trigger.get_next_fire_time(first, first + timedelta(seconds=1))
    assert first == datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
    assert second - first == timedelta(days=1)


def test_main_starts_the_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[BackgroundScheduler] = []

    class FakeScheduler(BackgroundScheduler):  # type: ignore[misc]
        def start(self, *args: object, **kwargs: object) -> None:
            started.append(self)

    monkeypatch.setattr(worker, "BlockingScheduler", FakeScheduler)
    worker.main()
    assert len(started) == 1
    assert [job.id for job in started[0].get_jobs()] == [worker.PURGE_DELETED_JOB_ID]
