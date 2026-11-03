"""ingestion: data access. Only this module's repository touches its tables."""

import uuid
from datetime import datetime

from sqlalchemy import Connection, exists, select, text, update
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.modules.ingestion.models import (
    FileKind,
    FileStatus,
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
) -> None:
    session.add(
        IngestionFile(
            id=new_id(),
            run_id=run_id,
            chain_id=chain_id,
            file_name=file_name,
            kind=kind,
            file_hash=file_hash,
            size_bytes=size_bytes,
            status=status,
            records=records,
            error=error,
            created_at=now,
        )
    )
    session.flush()
