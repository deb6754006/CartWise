"""ingestion: data access. Only this module's repository touches its tables."""

import uuid
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, exists, func, select, text, update
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.modules.ingestion.models import (
    AlertKind,
    FileKind,
    FileStatus,
    IngestionAlert,
    IngestionFile,
    IngestionRun,
    RunStatus,
)


def _lock_key(gov_chain_code: str) -> str:
    return f"ingest:{gov_chain_code}"


def try_lock(conn: Connection, gov_chain_code: str) -> bool:
    """A session-level advisory lock on conn: held until unlock, across transactions."""
    stmt = text("SELECT pg_try_advisory_lock(hashtext(:key))")
    return bool(conn.execute(stmt, {"key": _lock_key(gov_chain_code)}).scalar_one())


def unlock(conn: Connection, gov_chain_code: str) -> None:
    stmt = text("SELECT pg_advisory_unlock(hashtext(:key))")
    conn.execute(stmt, {"key": _lock_key(gov_chain_code)})


def abandon_running(session: Session, chain_id: uuid.UUID, now: datetime) -> int:
    """Marks the chain's runs still 'running' as abandoned. Only under the chain's lock: then no
    other run of it is alive. Returns how many."""
    result = session.execute(
        update(IngestionRun)
        .where(IngestionRun.chain_id == chain_id, IngestionRun.status == "running")
        .values(status="abandoned", finished_at=now)
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


def create_run(session: Session, chain_id: uuid.UUID, now: datetime) -> uuid.UUID:
    run_id = new_id()
    session.add(IngestionRun(id=run_id, chain_id=chain_id, started_at=now, status="running"))
    session.flush()
    return run_id


def finish_run(
    session: Session,
    run_id: uuid.UUID,
    *,
    status: RunStatus,
    files_seen: int,
    files_ingested: int,
    files_skipped: int,
    files_failed: int,
    records: int,
    error: str | None,
    now: datetime,
) -> None:
    session.execute(
        update(IngestionRun)
        .where(IngestionRun.id == run_id)
        .values(
            status=status,
            finished_at=now,
            files_seen=files_seen,
            files_ingested=files_ingested,
            files_skipped=files_skipped,
            files_failed=files_failed,
            records=records,
            error=error,
        )
    )


def was_ingested(session: Session, chain_id: uuid.UUID, file_name: str, file_hash: str) -> bool:
    """True if this exact file (AD-14) already has a succeeded row."""
    stmt = select(
        exists().where(
            IngestionFile.chain_id == chain_id,
            IngestionFile.file_name == file_name,
            IngestionFile.file_hash == file_hash,
            IngestionFile.status == "succeeded",
        )
    )
    return bool(session.execute(stmt).scalar_one())


def add_file(
    session: Session,
    *,
    run_id: uuid.UUID,
    chain_id: uuid.UUID,
    file_name: str,
    kind: FileKind,
    file_hash: str | None,
    size_bytes: int | None,
    status: FileStatus,
    records: int,
    error: str | None,
    now: datetime,
    series_key: str | None = None,
) -> None:
    session.add(
        IngestionFile(
            id=new_id(),
            run_id=run_id,
            chain_id=chain_id,
            file_name=file_name,
            kind=kind,
            series_key=series_key,
            file_hash=file_hash,
            size_bytes=size_bytes,
            status=status,
            records=records,
            error=error,
            created_at=now,
        )
    )
    session.flush()


# --- Health (Story 3.5) ---


def get_run(session: Session, run_id: uuid.UUID) -> IngestionRun | None:
    return session.get(IngestionRun, run_id)


def run_series_records(session: Session, run_id: uuid.UUID) -> dict[str, int]:
    """The run's succeeded files that have a series: series_key -> records."""
    stmt = select(IngestionFile.series_key, IngestionFile.records).where(
        IngestionFile.run_id == run_id,
        IngestionFile.status == "succeeded",
        IngestionFile.series_key.is_not(None),
    )
    return {key: records for key, records in session.execute(stmt) if key is not None}


def previous_series_records(
    session: Session,
    chain_id: uuid.UUID,
    run_id: uuid.UUID,
    series_keys: Collection[str],
    until: datetime,
) -> dict[str, int]:
    """For each series, the records of its latest succeeded file from another run, written no
    later than until (the run's start: runs of a chain never overlap). The newer id breaks a tie."""
    if not series_keys:
        return {}
    stmt = (
        select(IngestionFile.series_key, IngestionFile.records)
        .where(
            IngestionFile.chain_id == chain_id,
            IngestionFile.status == "succeeded",
            IngestionFile.series_key.in_(list(series_keys)),
            IngestionFile.run_id != run_id,
            IngestionFile.created_at <= until,
        )
        .order_by(
            IngestionFile.series_key, IngestionFile.created_at.desc(), IngestionFile.id.desc()
        )
        .ext(distinct_on(IngestionFile.series_key))
    )
    return {key: records for key, records in session.execute(stmt) if key is not None}


def chain_activity(
    session: Session, chain_ids: Collection[uuid.UUID]
) -> Sequence[tuple[uuid.UUID, datetime, datetime | None]]:
    """Each of these chains that has a run: (chain_id, its first run's start, the latest finish
    of a succeeded or partial run, or None)."""
    if not chain_ids:
        return []
    last_ok = func.max(IngestionRun.finished_at).filter(
        IngestionRun.status.in_(("succeeded", "partial"))
    )
    stmt = (
        select(IngestionRun.chain_id, func.min(IngestionRun.started_at), last_ok)
        .where(IngestionRun.chain_id.in_(list(chain_ids)))
        .group_by(IngestionRun.chain_id)
        .order_by(IngestionRun.chain_id)
    )
    return [(chain_id, first, last) for chain_id, first, last in session.execute(stmt)]


def open_alert(session: Session, chain_id: uuid.UUID, kind: AlertKind) -> IngestionAlert | None:
    """The chain's unresolved alert of this kind, locked for the rest of the transaction."""
    stmt = (
        select(IngestionAlert)
        .where(
            IngestionAlert.chain_id == chain_id,
            IngestionAlert.kind == kind,
            IngestionAlert.resolved_at.is_(None),
        )
        .with_for_update()
    )
    return session.execute(stmt).scalar_one_or_none()


def add_alert(
    session: Session,
    *,
    chain_id: uuid.UUID,
    kind: AlertKind,
    details: dict[str, Any],
    run_id: uuid.UUID | None,
    now: datetime,
) -> IngestionAlert | None:
    """Opens the alert. None if an open alert of this chain and kind already exists (another
    process opened it first): the caller selects that one."""
    alert_id = new_id()
    stmt = (
        insert(IngestionAlert)
        .values(
            id=alert_id,
            chain_id=chain_id,
            kind=kind,
            opened_at=now,
            last_sent_at=None,
            resolved_at=None,
            details=details,
            run_id=run_id,
        )
        .on_conflict_do_nothing(
            index_elements=[IngestionAlert.chain_id, IngestionAlert.kind],
            index_where=IngestionAlert.resolved_at.is_(None),
        )
        .returning(IngestionAlert.id)
    )
    if session.execute(stmt).scalar_one_or_none() is None:
        return None
    return session.get(IngestionAlert, alert_id)


def open_alerts_due(
    session: Session, kinds: Collection[AlertKind], sent_before: datetime
) -> list[IngestionAlert]:
    """The open alerts of these kinds never sent, or last sent at or before sent_before. Locked."""
    stmt = (
        select(IngestionAlert)
        .where(
            IngestionAlert.kind.in_(list(kinds)),
            IngestionAlert.resolved_at.is_(None),
            (IngestionAlert.last_sent_at.is_(None)) | (IngestionAlert.last_sent_at <= sent_before),
        )
        .order_by(IngestionAlert.opened_at, IngestionAlert.id)
        .with_for_update()
    )
    return list(session.execute(stmt).scalars())


def update_alert(
    session: Session,
    alert: IngestionAlert,
    *,
    details: dict[str, Any] | None = None,
    run_id: uuid.UUID | None = None,
    last_sent_at: datetime | None = None,
    resolved_at: datetime | None = None,
) -> None:
    """Sets the values given (None: left as it is)."""
    if details is not None:
        alert.details = details
    if run_id is not None:
        alert.run_id = run_id
    if last_sent_at is not None:
        alert.last_sent_at = last_sent_at
    if resolved_at is not None:
        alert.resolved_at = resolved_at
    session.flush()
