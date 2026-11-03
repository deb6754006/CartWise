"""Daily job: remove, for good, the accounts deleted more than 29 days ago (FR-6)."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.identity import service as identity_service

logger = logging.getLogger("app.worker.purge_deleted")


def run(
    session_factory: Callable[[], Session] = SessionLocal,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> identity_service.PurgeResult:
    """One run, with a session of its own. Logs (and returns) how many were purged / failed."""
    with session_factory() as session:
        result = identity_service.purge_deleted(session, now())
    log = logger.warning if result.failed else logger.info
    log("purge_deleted_done", extra={"purged": result.purged, "failed": result.failed})
    return result
