"""Ingestion health and operator alerts (Story 3.5), against Postgres: fake adapters, handlers
that report a given record count, and recording sinks. No network, no real SMTP."""

import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import make_engine
from app.modules.catalog import service as catalog_service
from app.modules.ingestion import health, repository, service
from app.modules.ingestion.adapters import RemoteFile, remote_file
from app.modules.ingestion.alerts import AlertMessage, EmailAlertSink, LogAlertSink
from app.modules.ingestion.service import RunSummary, ingest_chain
from app.worker.jobs import check_ingestion_health
from tests.integration.pg import alembic_config, create_database

pytestmark = pytest.mark.integration

CODE = "7290000000001"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def _price(store: int, stamp: str = "010000") -> str:
    return f"PriceFull{CODE}-001-{store:03d}-20261103-{stamp}.xml"


class Adapter:
    """Each file's bytes hold its record count: <Root n="..."/>. An Exception fails the fetch."""

    key = "fake"
    gov_chain_code = CODE
    name = "רשת בדויה"

    def __init__(
        self, files: dict[str, int | Exception], listing_error: Exception | None = None
    ) -> None:
        self.files = files
        self.listing_error = listing_error

    def list_files(self) -> list[RemoteFile]:
        if self.listing_error is not None:
            raise self.listing_error
        listed = [remote_file(name, f"https://files.test/{name}", CODE) for name in self.files]
        return [f for f in listed if f is not None]

    def fetch(self, file: RemoteFile) -> bytes:
        value = self.files[file.name]
        if isinstance(value, Exception):
            raise value
        return f'<Root n="{value}"/>'.encode()


def _count(session: Session, chain_id: uuid.UUID, root: Any) -> int:
    return int(root.get("n"))


HANDLERS: Any = {"stores": _count, "price_full": _count, "promo_full": _count}


class Recorder:
    def __init__(self) -> None:
        self.sent: list[AlertMessage] = []

    def send(self, alert: AlertMessage) -> None:
        self.sent.append(alert)


class FailingSMTP:
    def __init__(self, host: str, port: int, timeout: float) -> None:
        raise OSError("connection refused")


def _failing_email() -> EmailAlertSink:
    return EmailAlertSink(
        host="smtp.example.test",
        port=587,
        user="alerts@example.test",
        password="not-a-real-password",
        sender="alerts@example.test",
        recipients=["operator@example.test"],
        smtp_factory=FailingSMTP,  # type: ignore[arg-type]
    )


@pytest.fixture(scope="module")
def health_url(db_url: str) -> str:
    url = create_database(db_url, "cw_ingestion_health")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(health_url: str) -> Iterator[Engine]:
    eng = make_engine(health_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE promotion_products, promotions, price_observations, products, "
                "ingestion_alerts, "
                "ingestion_files, ingestion_runs, stores, user_clubs, clubs, chains"
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


def _ingest(
    factory: sessionmaker[Session],
    adapter: Adapter,
    sinks: list[Any],
    at: datetime = NOW,
) -> RunSummary:
    summary = ingest_chain(factory, adapter, HANDLERS, now=lambda: at, alert_sinks=sinks)
    assert summary is not None
    return summary


def _alerts(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM ingestion_alerts ORDER BY opened_at, id"))
        return [dict(row._mapping) for row in rows]


def _check(
    factory: sessionmaker[Session], sinks: list[Any], at: datetime
) -> dict[uuid.UUID, Any] | None:
    return check_ingestion_health.run(
        session_factory=factory, sinks=sinks, now=lambda: at, gov_chain_codes=[CODE]
    )


# --- record_drop ---


def test_a_good_run_alerts_nothing(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1): 1000}), [recorder])
    _ingest(factory, Adapter({_price(1, "070000"): 990}), [recorder], NOW + timedelta(hours=6))
    assert recorder.sent == []
    assert _alerts(engine) == []


def test_the_series_key_is_recorded(engine: Engine, factory: sessionmaker[Session]) -> None:
    stores = f"Stores{CODE}-000-202611030200.xml"
    _ingest(factory, Adapter({_price(5): 10, stores: 2}), [])
    with engine.connect() as conn:
        keys = dict(conn.execute(text("SELECT file_name, series_key FROM ingestion_files")).all())
    assert keys == {_price(5): "price_full:001-005", stores: "stores:-"}


def test_a_40_percent_drop_opens_one_alert(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1): 1000}), [recorder])
    later = NOW + timedelta(hours=6)
    summary = _ingest(factory, Adapter({_price(1, "070000"): 600}), [recorder], later)

    assert summary.status == "succeeded"
    [alert] = _alerts(engine)
    assert alert["kind"] == "record_drop"
    assert alert["details"]["prev"] == 1000
    assert alert["details"]["cur"] == 600
    assert alert["details"]["pct"] == 40
    assert alert["run_id"] == summary.run_id
    assert (alert["opened_at"], alert["last_sent_at"], alert["resolved_at"]) == (later, later, None)
    [sent] = recorder.sent
    assert (sent.chain, sent.kind, sent.details["pct"]) == ("רשת בדויה", "record_drop", 40)


def test_a_20_percent_drop_alerts_nothing(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1): 1000}), [recorder])
    _ingest(factory, Adapter({_price(1, "070000"): 800}), [recorder], NOW + timedelta(hours=6))
    assert recorder.sent == []
    assert _alerts(engine) == []


def test_the_drop_is_measured_per_series_not_per_run(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    # Store 2's file is unchanged, so skipped: only store 1 is compared, and it did not drop.
    _ingest(factory, Adapter({_price(1): 1000, _price(2): 5000}), [recorder])
    files: dict[str, int | Exception] = {_price(1, "070000"): 1000, _price(2): 5000}
    summary = _ingest(factory, Adapter(files), [recorder], NOW + timedelta(hours=6))
    assert (summary.files_ingested, summary.files_skipped, summary.records) == (1, 1, 1000)
    assert recorder.sent == []
    assert _alerts(engine) == []


def test_a_run_that_skipped_everything_leaves_the_drop_open(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1): 1000}), [recorder])
    dropped = {_price(1, "070000"): 600}
    _ingest(factory, Adapter(dropped), [recorder], NOW + timedelta(hours=6))
    # Two days later, so a held alert would be due again: still nothing is sent.
    summary = _ingest(factory, Adapter(dropped), [recorder], NOW + timedelta(hours=48))

    assert (summary.files_ingested, summary.files_failed, summary.files_skipped) == (0, 0, 1)
    [alert] = _alerts(engine)
    assert alert["resolved_at"] is None
    assert len(recorder.sent) == 1


def test_the_drop_is_resolved_on_recovery(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder, caplog: Any
) -> None:
    _ingest(factory, Adapter({_price(1): 1000}), [recorder])
    _ingest(factory, Adapter({_price(1, "070000"): 600}), [recorder], NOW + timedelta(hours=6))
    recovered = NOW + timedelta(hours=12)
    with caplog.at_level(logging.INFO, logger="app.ingestion.health"):
        _ingest(factory, Adapter({_price(1, "130000"): 990}), [recorder], recovered)

    [alert] = _alerts(engine)
    assert alert["resolved_at"] == recovered
    assert len(recorder.sent) == 1
    assert "ingestion_alert_resolved" in [r.getMessage() for r in caplog.records]


# --- file_errors ---


def _twenty(failed: int) -> dict[str, int | Exception]:
    return {_price(i): (OSError("down") if i < failed else 100) for i in range(20)}


def test_2_of_20_failed_files_open_file_errors(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    summary = _ingest(factory, Adapter(_twenty(2)), [recorder])
    assert (summary.status, summary.files_failed, summary.files_ingested) == ("partial", 2, 18)
    [alert] = _alerts(engine)
    assert alert["kind"] == "file_errors"
    assert alert["details"] == {"failed": 2, "attempted": 20, "pct": 10.0, "threshold": 5}
    [sent] = recorder.sent
    assert sent.kind == "file_errors"


def test_1_of_20_failed_files_is_at_the_threshold(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter(_twenty(1)), [recorder])
    assert recorder.sent == []
    assert _alerts(engine) == []


def test_a_failed_listing_opens_file_errors(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    summary = _ingest(factory, Adapter({}, listing_error=OSError("portal down")), [recorder])
    assert summary.status == "failed"
    [alert] = _alerts(engine)
    assert alert["kind"] == "file_errors"
    assert alert["details"]["pct"] == 100
    assert alert["details"]["error"] == "OSError: portal down"
    assert len(recorder.sent) == 1


def test_file_errors_resolve_after_a_clean_run(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter(_twenty(2)), [recorder])
    later = NOW + timedelta(hours=6)
    _ingest(factory, Adapter({_price(0, "070000"): 100}), [recorder], later)
    [alert] = _alerts(engine)
    assert alert["resolved_at"] == later
    assert len(recorder.sent) == 1


# --- stale ---


def test_a_day_without_ingestion_opens_stale_once(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1): 100}), [], NOW - timedelta(hours=25))

    actions = _check(factory, [recorder], NOW)
    assert actions is not None
    assert list(actions.values()) == ["opened"]
    [alert] = _alerts(engine)
    assert alert["kind"] == "stale"
    assert alert["run_id"] is None
    assert alert["details"]["hours"] == 25
    assert alert["last_sent_at"] == NOW
    assert len(recorder.sent) == 1

    # An hour later: still stale, not sent again.
    actions = _check(factory, [recorder], NOW + timedelta(hours=1))
    assert actions is not None
    assert list(actions.values()) == ["held"]
    assert len(recorder.sent) == 1
    assert len(_alerts(engine)) == 1


def test_a_stale_alert_is_sent_again_after_a_day(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1): 100}), [], NOW - timedelta(hours=25))
    _check(factory, [recorder], NOW)
    again = NOW + timedelta(hours=25)
    actions = _check(factory, [recorder], again)
    assert actions is not None
    assert list(actions.values()) == ["sent_again"]
    [alert] = _alerts(engine)
    assert (alert["opened_at"], alert["last_sent_at"]) == (NOW, again)
    assert len(recorder.sent) == 2


def test_stale_is_resolved_when_ingestion_is_back(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1): 100}), [], NOW - timedelta(hours=25))
    _check(factory, [recorder], NOW)
    _ingest(factory, Adapter({_price(1, "120000"): 100}), [], NOW + timedelta(hours=1))
    actions = _check(factory, [recorder], NOW + timedelta(hours=2))
    assert actions is not None
    assert list(actions.values()) == ["resolved"]
    [alert] = _alerts(engine)
    assert alert["resolved_at"] == NOW + timedelta(hours=2)
    assert len(recorder.sent) == 1


def test_a_skipped_only_run_counts_as_an_update(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    files: dict[str, int | Exception] = {_price(1): 100}
    _ingest(factory, Adapter(files), [], NOW - timedelta(hours=30))
    summary = _ingest(factory, Adapter(files), [], NOW - timedelta(hours=1))
    assert (summary.status, summary.files_skipped) == ("succeeded", 1)
    actions = _check(factory, [recorder], NOW)
    assert actions is not None
    assert list(actions.values()) == ["none"]
    assert recorder.sent == []


def test_a_chain_that_only_failed_is_measured_from_its_first_run(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    failing = Adapter({}, listing_error=OSError("down"))
    _ingest(factory, failing, [], NOW - timedelta(hours=23))
    actions = _check(factory, [recorder], NOW)
    assert actions is not None
    assert list(actions.values()) == ["none"]
    actions = _check(factory, [recorder], NOW + timedelta(hours=2))
    assert actions is not None
    assert list(actions.values()) == ["opened"]
    [alert] = [a for a in _alerts(engine) if a["kind"] == "stale"]
    assert alert["details"]["last_success_at"] is None


def test_a_chain_that_never_ran_is_not_alerted(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    with factory() as session:
        catalog_service.ensure_chain(session, CODE, "רשת בדויה")
        session.commit()
    assert _check(factory, [recorder], NOW) == {}
    assert recorder.sent == []
    assert _alerts(engine) == []


# --- failures ---


def test_a_failed_email_keeps_the_alert_and_the_run(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder, caplog: Any
) -> None:
    sinks = [LogAlertSink(), _failing_email()]
    with caplog.at_level(logging.WARNING):
        summary = _ingest(factory, Adapter(_twenty(2)), sinks)

    assert summary.status == "partial"
    [alert] = _alerts(engine)
    assert alert["kind"] == "file_errors"
    # The log took it: sent, so the repeat interval applies, not a resend at every check.
    assert alert["last_sent_at"] == NOW
    failures = [r for r in caplog.records if r.getMessage() == "ingestion_alert_send_failed"]
    [failure] = failures
    assert failure.error == "OSError"  # type: ignore[attr-defined]
    assert failure.sink == "EmailAlertSink"  # type: ignore[attr-defined]
    assert "not-a-real-password" not in caplog.text

    later = NOW + timedelta(hours=1)
    _ingest(factory, Adapter({**_twenty(2), _price(2, "070000"): 100}), [recorder], later)
    assert recorder.sent == []
    [alert] = _alerts(engine)
    assert alert["last_sent_at"] == NOW


def test_an_alert_no_sink_took_is_sent_at_the_next_check(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    summary = _ingest(factory, Adapter(_twenty(2)), [_failing_email()])
    assert summary.status == "partial"
    [alert] = _alerts(engine)
    assert alert["last_sent_at"] is None

    # The next run that still sees the errors sends it, though no repeat interval has passed.
    later = NOW + timedelta(hours=1)
    _ingest(factory, Adapter({**_twenty(2), _price(2, "070000"): 100}), [recorder], later)
    assert len(recorder.sent) == 1
    [alert] = _alerts(engine)
    assert alert["last_sent_at"] == later


def test_a_failed_email_does_not_fail_the_job(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    _ingest(factory, Adapter({_price(1): 100}), [], NOW - timedelta(hours=25))
    actions = _check(factory, [LogAlertSink(), _failing_email()], NOW)
    assert actions is not None
    assert list(actions.values()) == ["opened"]
    [alert] = _alerts(engine)
    assert alert["last_sent_at"] == NOW


def test_a_failing_evaluation_leaves_the_run_as_it_is(
    engine: Engine, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(health, "evaluate_run", broken)
    with caplog.at_level(logging.WARNING, logger="app.ingestion"):
        summary = _ingest(factory, Adapter({_price(1): 100}), [])
    assert summary.status == "succeeded"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM ingestion_runs")).scalar_one() == "succeeded"
    assert "ingestion_health_failed" in [r.getMessage() for r in caplog.records]


def test_the_job_never_raises(
    factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(check_ingestion_health, "check_stale", broken)
    assert _check(factory, [], NOW) is None


def test_one_open_alert_per_chain_and_kind(engine: Engine, factory: sessionmaker[Session]) -> None:
    with factory() as session:
        chain_id = catalog_service.ensure_chain(session, CODE, "רשת בדויה")
        repository.add_alert(
            session, chain_id=chain_id, kind="stale", details={}, run_id=None, now=NOW
        )
        session.commit()
    with factory() as session:
        again = repository.add_alert(
            session, chain_id=chain_id, kind="stale", details={}, run_id=None, now=NOW
        )
        assert again is None
    assert len(_alerts(engine)) == 1


def test_an_alert_opened_by_another_process_meanwhile(
    engine: Engine,
    factory: sessionmaker[Session],
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ingest(factory, Adapter({_price(1): 100}), [], NOW - timedelta(hours=25))
    real_open_alert = repository.open_alert
    calls: list[int] = []

    def raced(session: Session, chain_id: uuid.UUID, kind: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            # The CLI and the job: the other one opens (and sends) it between read and insert.
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO ingestion_alerts (id, chain_id, kind, opened_at, "
                        "last_sent_at, details) VALUES (:id, :chain, 'stale', :at, :at, '{}')"
                    ),
                    {"id": uuid.uuid4(), "chain": chain_id, "at": NOW},
                )
            return None
        return real_open_alert(session, chain_id, kind)

    monkeypatch.setattr(health.repository, "open_alert", raced)
    actions = _check(factory, [recorder], NOW)
    assert actions is not None
    assert list(actions.values()) == ["held"]
    [alert] = _alerts(engine)
    assert alert["details"]["hours"] == 25
    assert recorder.sent == []


OTHER_CODE = "7290000000002"


def test_a_failing_chain_does_not_roll_back_another(
    engine: Engine,
    factory: sessionmaker[Session],
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = Adapter({f"PriceFull{OTHER_CODE}-001-001-20261103-010000.xml": 100})
    other.gov_chain_code = OTHER_CODE
    other.name = "רשת אחרת"
    _ingest(factory, Adapter({_price(1): 100}), [], NOW - timedelta(hours=25))
    real = health._raise_or_resolve

    def fails_for_the_other(session: Session, **kwargs: Any) -> Any:
        if kwargs["chain"] == "רשת אחרת":
            raise RuntimeError("db down")
        return real(session, **kwargs)

    # The other chain only needs a run row; its files are not of the fake chain code.
    with factory() as session:
        other_id = catalog_service.ensure_chain(session, OTHER_CODE, "רשת אחרת")
        repository.create_run(session, other_id, NOW - timedelta(hours=30))
        session.commit()
    monkeypatch.setattr(health, "_raise_or_resolve", fails_for_the_other)
    actions = check_ingestion_health.run(
        session_factory=factory,
        sinks=[recorder],
        now=lambda: NOW,
        gov_chain_codes=[CODE, OTHER_CODE],
    )
    assert actions is not None
    assert list(actions.values()) == ["opened"]
    [alert] = _alerts(engine)
    assert alert["last_sent_at"] == NOW
    assert len(recorder.sent) == 1


# --- deferred from 3.2 ---


def test_a_failed_unlock_still_returns_and_frees_the_chain(
    factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_unlock = repository.unlock
    calls: list[int] = []

    def unlock_fails_once(conn: Any, code: str) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("connection lost")
        real_unlock(conn, code)

    monkeypatch.setattr(service.repository, "unlock", unlock_fails_once)
    first = ingest_chain(factory, Adapter({_price(1): 100}), HANDLERS, alert_sinks=[])
    assert first is not None
    assert first.status == "succeeded"
    # The connection that may have kept the lock was invalidated: the next run is not locked out.
    second = ingest_chain(factory, Adapter({_price(1, "070000"): 100}), HANDLERS, alert_sinks=[])
    assert second is not None
    assert second.status == "succeeded"
    assert len(calls) == 2


# --- review follow-ups ---


def test_a_chain_no_longer_configured_is_not_stale(
    factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1): 100}), [], NOW - timedelta(hours=25))
    actions = check_ingestion_health.run(
        session_factory=factory,
        sinks=[recorder],
        now=lambda: NOW,
        gov_chain_codes=["7290000000009"],
    )
    assert actions == {}
    assert recorder.sent == []


def test_a_recent_partial_run_counts_as_an_update(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1): 100}), [], NOW - timedelta(hours=30))
    files: dict[str, int | Exception] = {_price(1, "070000"): 100, _price(2): OSError("down")}
    summary = _ingest(factory, Adapter(files), [], NOW - timedelta(hours=1))
    assert summary.status == "partial"
    actions = _check(factory, [recorder], NOW)
    assert actions is not None
    assert list(actions.values()) == ["none"]
    assert [a for a in _alerts(engine) if a["kind"] == "stale"] == []
    assert [a.kind for a in recorder.sent if a.kind == "stale"] == []


def test_the_drop_is_against_the_latest_earlier_file(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1, "010000"): 100}), [recorder])
    _ingest(factory, Adapter({_price(1, "070000"): 1000}), [recorder], NOW + timedelta(hours=6))
    _ingest(factory, Adapter({_price(1, "130000"): 600}), [recorder], NOW + timedelta(hours=12))
    [alert] = _alerts(engine)
    assert alert["kind"] == "record_drop"
    assert (alert["details"]["prev"], alert["details"]["cur"]) == (1000, 600)
    assert alert["details"]["series_keys"] == ["price_full:001-001"]


def test_a_drop_is_not_resolved_by_a_run_of_other_series(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1): 1000, _price(2): 1000}), [recorder])
    # Store 1 drops; store 2 is unchanged (skipped).
    files: dict[str, int | Exception] = {_price(1, "070000"): 600, _price(2): 1000}
    _ingest(factory, Adapter(files), [recorder], NOW + timedelta(hours=6))
    # Store 2 changes and is fine; store 1 is still low, skipped: the drop stays open.
    files = {_price(1, "070000"): 600, _price(2, "130000"): 1000}
    _ingest(factory, Adapter(files), [recorder], NOW + timedelta(hours=12))
    [alert] = _alerts(engine)
    assert alert["resolved_at"] is None
    # Store 1 recovers: resolved.
    files = {_price(1, "190000"): 990, _price(2, "130000"): 1000}
    later = NOW + timedelta(hours=18)
    _ingest(factory, Adapter(files), [recorder], later)
    [alert] = _alerts(engine)
    assert alert["resolved_at"] == later
    assert len(recorder.sent) == 1


def test_the_threshold_is_compared_before_rounding(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    _ingest(factory, Adapter({_price(1): 10000}), [recorder])
    # 30.04%: over 30, though it rounds to 30.0.
    _ingest(factory, Adapter({_price(1, "070000"): 6996}), [recorder], NOW + timedelta(hours=6))
    [alert] = _alerts(engine)
    assert alert["kind"] == "record_drop"
    assert alert["details"]["pct"] == 30.0


def test_the_hourly_job_reminds_of_open_run_alerts(
    engine: Engine, factory: sessionmaker[Session], recorder: Recorder
) -> None:
    def errors_sent() -> int:
        return len([a for a in recorder.sent if a.kind == "file_errors"])

    _ingest(factory, Adapter(_twenty(2)), [recorder])
    assert errors_sent() == 1
    _check(factory, [recorder], NOW + timedelta(hours=1))
    assert errors_sent() == 1
    _check(factory, [recorder], NOW + timedelta(hours=24))
    assert errors_sent() == 2
    [alert] = [a for a in _alerts(engine) if a["kind"] == "file_errors"]
    assert alert["last_sent_at"] == NOW + timedelta(hours=24)
    assert alert["resolved_at"] is None
    _check(factory, [recorder], NOW + timedelta(hours=25))
    assert errors_sent() == 2


def test_the_default_sinks_are_wired(
    engine: Engine, factory: sessionmaker[Session], caplog: Any
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.ingestion.alerts"):
        summary = ingest_chain(factory, Adapter(_twenty(2)), HANDLERS, now=lambda: NOW)
    assert summary is not None
    assert "ingestion_alert" in [r.getMessage() for r in caplog.records]
    [alert] = _alerts(engine)
    assert alert["last_sent_at"] == NOW
