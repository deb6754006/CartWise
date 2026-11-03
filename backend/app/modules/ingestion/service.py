"""ingestion: business logic. Other modules use ingestion data only through this file.

One run of one chain (`ingest_chain`): list the chain's files, keep the latest of each kind and
store, and take them one by one: download, hash, skip a file already ingested (AD-14), decode, and
hand the XML to the handler of its kind. Each file has a transaction of its own: a broken file is
rolled back and recorded as failed, and the run goes on to the next one.

The handlers write what is in the files: the Stores handler writes the chain's stores and their
locations (Story 3.3, ingestion.stores). The price and promotion handlers still only count
records (Story 3.4 replaces them).

A file URL can carry a signature, so URLs are never logged, and are removed from stored errors.
"""

import hashlib
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from xml.etree.ElementTree import Element

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.modules.catalog import service as catalog_service
from app.modules.geo.service import Geocoder
from app.modules.ingestion import repository
from app.modules.ingestion.adapters import (
    MAX_DOWNLOAD_BYTES,
    ChainAdapter,
    DownloadTooLargeError,
    RemoteFile,
    latest_per_store,
    redact_urls,
)
from app.modules.ingestion.decode import count_elements, decode_xml
from app.modules.ingestion.models import FileKind, RunStatus
from app.modules.ingestion.stores import stores_handler

logger = logging.getLogger("app.ingestion")

MAX_ERROR_LENGTH = 500

# (session, chain_id, root) -> how many records the file had. Runs inside the file's transaction.
type Handler = Callable[[Session, uuid.UUID, Element], int]
type Clock = Callable[[], datetime]
type FileOutcome = Literal["ingested", "skipped", "failed"]


def count_handler(tag: str) -> Handler:
    """A handler that writes nothing and counts the elements named tag."""

    def handle(_session: Session, _chain_id: uuid.UUID, root: Element) -> int:
        return count_elements(root, tag)

    return handle


def handlers_with_geocoder(geocoder: Geocoder | None) -> Mapping[FileKind, Handler]:
    """The handlers of every kind. Stores are geocoded with geocoder (None: not geocoded)."""
    return {
        "stores": stores_handler(geocoder),
        # Story 3.4 replaces these.
        "price_full": count_handler("Item"),
        "promo_full": count_handler("Promotion"),
    }


# With no geocoder, so no network: the scheduled job passes handlers with the real geocoder.
DEFAULT_HANDLERS: Mapping[FileKind, Handler] = handlers_with_geocoder(None)


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: uuid.UUID
    chain_key: str
    status: RunStatus
    files_seen: int
    files_ingested: int
    files_skipped: int
    files_failed: int
    records: int


def error_text(exc: BaseException) -> str:
    """'<ExceptionType>: <message>', with any URL removed, at most MAX_ERROR_LENGTH long."""
    message = redact_urls(str(exc))
    full = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    return full[:MAX_ERROR_LENGTH]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def run_status(listed: bool, ok: int, failed: int) -> RunStatus:
    """ok counts the files ingested or skipped."""
    if not listed:
        return "failed"
    if failed == 0:
        return "succeeded"
    return "partial" if ok > 0 else "failed"


def _ingest_file(
    session_factory: Callable[[], Session],
    adapter: ChainAdapter,
    handlers: Mapping[FileKind, Handler],
    chain_id: uuid.UUID,
    run_id: uuid.UUID,
    file: RemoteFile,
    now: Clock,
) -> tuple[FileOutcome, int]:
    digest: str | None = None
    size: int | None = None
    try:
        data = adapter.fetch(file)
        size = len(data)
        if size > MAX_DOWNLOAD_BYTES:
            raise DownloadTooLargeError(f"download over {MAX_DOWNLOAD_BYTES} bytes")
        digest = hashlib.sha256(data).hexdigest()
        with session_factory() as session:
            if repository.was_ingested(session, chain_id, file.name, digest):
                return "skipped", 0
            root = decode_xml(data)
            del data
            records = handlers[file.kind](session, chain_id, root)
            del root
            repository.add_file(
                session,
                run_id=run_id,
                chain_id=chain_id,
                file_name=file.name,
                kind=file.kind,
                file_hash=digest,
                size_bytes=size,
                status="succeeded",
                records=records,
                error=None,
                now=now(),
            )
            session.commit()
        return "ingested", records
    except Exception as exc:
        # Leaving the with block rolled back whatever the handler wrote for this file.
        logger.warning(
            "ingestion_file_failed",
            extra={"chain": adapter.key, "file_name": file.name, "error": type(exc).__name__},
        )
        with session_factory() as session:
            repository.add_file(
                session,
                run_id=run_id,
                chain_id=chain_id,
                file_name=file.name,
                kind=file.kind,
                file_hash=digest,
                size_bytes=size,
                status="failed",
                records=0,
                error=error_text(exc),
                now=now(),
            )
            session.commit()
        return "failed", 0


def _run(
    session_factory: Callable[[], Session],
    adapter: ChainAdapter,
    handlers: Mapping[FileKind, Handler],
    now: Clock,
) -> RunSummary:
    """One run, under the chain's lock."""
    with session_factory() as session:
        chain_id = catalog_service.ensure_chain(session, adapter.gov_chain_code, adapter.name)
        abandoned = repository.abandon_running(session, chain_id, now())
        run_id = repository.create_run(session, chain_id, now())
        session.commit()
    if abandoned:
        logger.warning("ingestion_runs_abandoned", extra={"chain": adapter.key, "runs": abandoned})

    counts: dict[FileOutcome, int] = {"ingested": 0, "skipped": 0, "failed": 0}
    records = 0
    error: str | None = None
    selected: list[RemoteFile] = []
    try:
        selected = latest_per_store(adapter.list_files())
        listed = True
    except Exception as exc:
        listed = False
        error = error_text(exc)
        logger.warning(
            "ingestion_list_failed", extra={"chain": adapter.key, "error": type(exc).__name__}
        )

    for file in selected:
        outcome, file_records = _ingest_file(
            session_factory, adapter, handlers, chain_id, run_id, file, now
        )
        counts[outcome] += 1
        records += file_records

    status = run_status(listed, counts["ingested"] + counts["skipped"], counts["failed"])
    if listed and not selected:
        # A portal that lists nothing has most likely changed its format.
        status, error = "failed", "no files listed"
    elif listed and status == "failed":
        error = f"all {counts['failed']} files failed"
    elif status == "partial":
        error = f"{counts['failed']} of {len(selected)} files failed"
    with session_factory() as session:
        repository.finish_run(
            session,
            run_id,
            status=status,
            files_seen=len(selected),
            files_ingested=counts["ingested"],
            files_skipped=counts["skipped"],
            files_failed=counts["failed"],
            records=records,
            error=error,
            now=now(),
        )
        session.commit()

    summary = RunSummary(
        run_id=run_id,
        chain_key=adapter.key,
        status=status,
        files_seen=len(selected),
        files_ingested=counts["ingested"],
        files_skipped=counts["skipped"],
        files_failed=counts["failed"],
        records=records,
    )
    log = logger.info if status == "succeeded" else logger.warning
    log(
        "ingestion_run_done",
        extra={
            "chain": adapter.key,
            "run_id": str(run_id),
            "status": status,
            "files_seen": summary.files_seen,
            "files_ingested": summary.files_ingested,
            "files_skipped": summary.files_skipped,
            "files_failed": summary.files_failed,
            "records": records,
        },
    )
    return summary


def ingest_chain(
    session_factory: Callable[[], Session],
    adapter: ChainAdapter,
    handlers: Mapping[FileKind, Handler] = DEFAULT_HANDLERS,
    now: Clock = _utcnow,
) -> RunSummary | None:
    """One run of one chain. None, with no run row, if a run of the chain is already going on.

    The lock is a Postgres advisory lock, held for the whole run on a connection of its own (not
    one of the files' sessions), in autocommit so it holds no transaction open.
    """
    with session_factory() as probe:
        bind = probe.get_bind()
    if not isinstance(bind, Engine):
        raise TypeError("ingest_chain needs sessions bound to an Engine")
    with bind.connect() as lock_conn:
        lock_conn.execution_options(isolation_level="AUTOCOMMIT")
        if not repository.try_lock(lock_conn, adapter.gov_chain_code):
            logger.info("ingestion_run_locked", extra={"chain": adapter.key})
            return None
        try:
            return _run(session_factory, adapter, handlers, now)
        finally:
            try:
                repository.unlock(lock_conn, adapter.gov_chain_code)
            except Exception as exc:
                # A connection that may still hold the lock never goes back to the pool.
                logger.warning(
                    "ingestion_unlock_failed",
                    extra={"chain": adapter.key, "error": type(exc).__name__},
                )
                lock_conn.invalidate()
