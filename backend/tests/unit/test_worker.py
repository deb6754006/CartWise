"""The worker's schedule: purge_deleted once a day (Story 1.7), each chain's ingestion at least
every 6 hours (Story 3.2), and the ingestion's health every hour (Story 3.5). No database, no
running loop."""

import itertools
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.modules.ingestion.adapters import CHAIN_KEYS
from app.modules.ingestion.service import RunSummary
from app.worker import main as worker
from app.worker.jobs import check_ingestion_health, ingest_chain, purge_deleted

ALL_JOB_IDS = [
    worker.PURGE_DELETED_JOB_ID,
    "ingest_shufersal",
    "ingest_rami_levy",
    "ingest_carrefour",
    worker.CHECK_INGESTION_HEALTH_JOB_ID,
]


def test_jobs() -> None:
    scheduler = worker.schedule_jobs(BackgroundScheduler(timezone="UTC"))
    assert [job.id for job in scheduler.get_jobs()] == ALL_JOB_IDS


def test_purge_deleted_is_scheduled_once_a_day() -> None:
    scheduler = worker.schedule_jobs(BackgroundScheduler(timezone="UTC"))
    job = scheduler.get_job(worker.PURGE_DELETED_JOB_ID)
    assert job.func is purge_deleted.run
    assert job.max_instances == 1

    start = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    first = job.trigger.get_next_fire_time(None, start)
    second = job.trigger.get_next_fire_time(first, first + timedelta(seconds=1))
    assert first == datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
    assert second - first == timedelta(days=1)


@pytest.mark.parametrize(
    ("job_id", "chain_key"),
    [
        ("ingest_shufersal", "shufersal"),
        ("ingest_rami_levy", "rami_levy"),
        ("ingest_carrefour", "carrefour"),
    ],
)
def test_each_chain_is_ingested_at_least_every_6_hours(job_id: str, chain_key: str) -> None:
    before = datetime.now(UTC)
    scheduler = worker.schedule_jobs(BackgroundScheduler(timezone="UTC"))
    job = scheduler.get_job(job_id)
    assert job.func is ingest_chain.run
    assert job.args == (chain_key,)
    assert job.max_instances == 1
    assert job.coalesce is True

    # The first run comes soon after the worker starts, not a whole interval later.
    assert before < job.next_run_time <= before + timedelta(minutes=15)
    first = job.trigger.get_next_fire_time(None, before)
    second = job.trigger.get_next_fire_time(first, first + timedelta(seconds=1))
    gap = second - first
    assert gap <= timedelta(hours=6)
    assert gap == timedelta(hours=get_settings().INGEST_INTERVAL_HOURS)


def test_main_starts_the_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[BackgroundScheduler] = []

    class FakeScheduler(BackgroundScheduler):  # type: ignore[misc]
        def start(self, *args: object, **kwargs: object) -> None:
            started.append(self)

    monkeypatch.setattr(worker, "BlockingScheduler", FakeScheduler)
    worker.main()
    assert len(started) == 1
    assert [job.id for job in started[0].get_jobs()] == ALL_JOB_IDS


def test_ingest_job_never_raises() -> None:
    def broken() -> dict[str, ingest_chain.ChainAdapter]:
        raise RuntimeError("boom")

    assert ingest_chain.run("shufersal", adapters=broken) is None
    assert ingest_chain.run("nowhere", adapters=dict) is None


def test_ingest_job_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert ingest_chain.main([]) == 2
    assert ingest_chain.main(["nowhere"]) == 2
    assert "shufersal|rami_levy|carrefour" in capsys.readouterr().out


def test_ingest_jobs_are_staggered_and_tolerate_misfires() -> None:
    scheduler = worker.schedule_jobs(BackgroundScheduler(timezone="UTC"))
    jobs = [scheduler.get_job(f"ingest_{key}") for key in CHAIN_KEYS]
    times = [job.next_run_time for job in jobs]
    assert all(a < b for a, b in itertools.pairwise(times))
    hours = get_settings().INGEST_INTERVAL_HOURS
    assert all(job.misfire_grace_time == hours * 3600 for job in jobs)


def _summary(status: str) -> RunSummary:
    return RunSummary(uuid.uuid4(), "shufersal", status, 3, 3, 0, 0, 7)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("result", "code"),
    [(_summary("succeeded"), 0), (_summary("partial"), 1), (None, 1)],
)
def test_ingest_job_exit_code(
    monkeypatch: pytest.MonkeyPatch, result: RunSummary | None, code: int
) -> None:
    monkeypatch.setattr(ingest_chain, "run", lambda key: result)
    assert ingest_chain.main(["shufersal"]) == code


def test_ingestion_health_is_checked_every_hour() -> None:
    before = datetime.now(UTC)
    scheduler = worker.schedule_jobs(BackgroundScheduler(timezone="UTC"))
    job = scheduler.get_job(worker.CHECK_INGESTION_HEALTH_JOB_ID)
    assert job.func is check_ingestion_health.run
    assert job.max_instances == 1
    assert job.coalesce is True
    # A few minutes after start, not at once and not a whole hour later.
    assert before + timedelta(minutes=1) < job.next_run_time <= before + timedelta(minutes=15)
    first = job.trigger.get_next_fire_time(None, before)
    second = job.trigger.get_next_fire_time(first, first + timedelta(seconds=1))
    assert second - first == timedelta(hours=1)


def test_health_job_never_raises() -> None:
    def broken() -> object:
        raise RuntimeError("boom")

    assert check_ingestion_health.run(session_factory=broken) is None  # type: ignore[arg-type]


def test_health_job_usage_and_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check_ingestion_health.main(["extra"]) == 2
    assert "check_ingestion_health" in capsys.readouterr().out
    monkeypatch.setattr(check_ingestion_health, "run", lambda: None)
    assert check_ingestion_health.main([]) == 1
    chain_id = uuid.uuid4()
    monkeypatch.setattr(check_ingestion_health, "run", lambda: {chain_id: "opened"})
    assert check_ingestion_health.main([]) == 0
    assert f"{chain_id} stale: opened" in capsys.readouterr().out
