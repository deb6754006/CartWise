"""ingestion: health checks and operator alerts (Story 3.5, FR-16).

Three conditions, each with at most one open alert per chain:
- stale: no succeeded or partial run finished in the last INGEST_STALE_HOURS. Checked by the
  hourly job (check_stale), for the configured chains only. A chain with no such run at all is
  measured from its first run; a chain that never ran is not alerted on.
- record_drop: the run's succeeded files hold more than INGEST_RECORD_DROP_PCT fewer records than
  the previous succeeded file of each of their series (the PriceFull of one store, ...). Compared
  per series, not per run: most files of a run are skipped as unchanged (AD-14). An open drop is
  resolved only by a run that compared its series (see _drop_resolvable).
- file_errors: more than INGEST_FILE_ERROR_PCT of the files the run tried failed. A failed run
  that tried no file (its listing failed) counts as 100%.
record_drop and file_errors are checked at the end of each run (evaluate_run). A run with nothing
to measure (every file skipped) leaves them as they are. The hourly job also reminds of every open
alert not sent for INGEST_ALERT_REPEAT_HOURS (remind_open).

An alert is sent when it opens, and again every INGEST_ALERT_REPEAT_HOURS while it holds. It
counts as sent when at least one sink took it; a failing sink is logged. When the condition no
longer holds it is resolved, with a log line and no message.

Each alert is committed on its own (opened before it is sent), so a failure with one chain or kind
loses nothing already sent for another.
"""

import logging
import uuid
from collections.abc import Callable, Collection, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.catalog import service as catalog_service
from app.modules.ingestion import repository
from app.modules.ingestion.alerts import AlertMessage, AlertSink
from app.modules.ingestion.models import AlertKind, IngestionAlert, IngestionRun

logger = logging.getLogger("app.ingestion.health")

type AlertAction = Literal["opened", "sent_again", "held", "resolved", "none"]


def _pct(part: float, whole: float) -> float:
    """Unrounded: thresholds are compared with this. Round only for details."""
    return part / whole * 100


def _chain_names(session: Session) -> dict[uuid.UUID, str]:
    return {chain.id: chain.name for chain in catalog_service.list_chains(session)}


def _send(sinks: Sequence[AlertSink], message: AlertMessage) -> bool:
    """True if at least one sink took the message. A failing sink is logged (its error type)."""
    sent = False
    for sink in sinks:
        try:
            sink.send(message)
            sent = True
        except Exception as exc:
            logger.warning(
                "ingestion_alert_send_failed",
                extra={
                    "chain": message.chain,
                    "kind": message.kind,
                    "sink": type(sink).__name__,
                    "error": type(exc).__name__,
                },
            )
    return sent


def _deliver(
    session: Session,
    alert: IngestionAlert,
    chain: str,
    sinks: Sequence[AlertSink],
    now: datetime,
) -> None:
    message = AlertMessage(
        chain=chain, kind=alert.kind, details=alert.details, opened_at=alert.opened_at, at=now
    )
    if _send(sinks, message):
        repository.update_alert(session, alert, last_sent_at=now)
    session.commit()


def _raise_or_resolve(
    session: Session,
    *,
    chain_id: uuid.UUID,
    chain: str,
    kind: AlertKind,
    holds: bool,
    details: dict[str, Any] | Callable[[IngestionAlert | None], dict[str, Any]],
    run_id: uuid.UUID | None,
    sinks: Sequence[AlertSink],
    settings: Settings,
    now: datetime,
    may_resolve: Callable[[IngestionAlert], bool] | None = None,
) -> AlertAction:
    """Opens, sends again, or resolves the chain's alert of this kind, and commits. details may
    be computed from the open alert (None if there is none). may_resolve can keep an open alert
    open when the condition does not hold."""
    alert = repository.open_alert(session, chain_id, kind)
    if not holds:
        if alert is None or (may_resolve is not None and not may_resolve(alert)):
            session.commit()
            return "none"
        repository.update_alert(session, alert, resolved_at=now)
        session.commit()
        logger.info(
            "ingestion_alert_resolved",
            extra={"chain": chain, "kind": kind, "alert_id": str(alert.id)},
        )
        return "resolved"

    action: AlertAction = "sent_again"
    if alert is None:
        new = details(None) if callable(details) else details
        alert = repository.add_alert(
            session, chain_id=chain_id, kind=kind, details=new, run_id=run_id, now=now
        )
        if alert is not None:
            session.commit()  # the row exists before anything is sent
            _deliver(session, alert, chain, sinks, now)
            return "opened"
        # Another process opened it between the read and the insert.
        alert = repository.open_alert(session, chain_id, kind)
        if alert is None:
            raise RuntimeError("open alert vanished")
    new = details(alert) if callable(details) else details
    repository.update_alert(session, alert, details=new, run_id=run_id)
    repeat = timedelta(hours=settings.INGEST_ALERT_REPEAT_HOURS)
    if alert.last_sent_at is not None and now - alert.last_sent_at < repeat:
        session.commit()
        return "held"
    session.commit()
    _deliver(session, alert, chain, sinks, now)
    return action


def _guarded(
    session: Session, chain: str, kind: AlertKind, check: Callable[[], AlertAction]
) -> AlertAction | None:
    """Runs one check. A failure is rolled back and logged, and the next check goes on."""
    try:
        return check()
    except Exception as exc:
        session.rollback()
        logger.warning(
            "ingestion_health_check_failed",
            extra={"chain": chain, "kind": kind, "error": type(exc).__name__},
        )
        return None


def _file_errors(
    session: Session,
    run: IngestionRun,
    chain: str,
    sinks: Sequence[AlertSink],
    settings: Settings,
    now: datetime,
) -> AlertAction:
    attempted = run.files_ingested + run.files_failed
    failed_pct = _pct(run.files_failed, attempted) if attempted > 0 else 100.0
    details: dict[str, Any] = {
        "failed": run.files_failed,
        "attempted": attempted,
        "pct": round(failed_pct, 1),
        "threshold": settings.INGEST_FILE_ERROR_PCT,
    }
    if attempted == 0:
        details["error"] = run.error
    return _raise_or_resolve(
        session,
        chain_id=run.chain_id,
        chain=chain,
        kind="file_errors",
        holds=failed_pct > settings.INGEST_FILE_ERROR_PCT,
        details=details,
        run_id=run.id,
        sinks=sinks,
        settings=settings,
        now=now,
    )


def _record_drop(
    session: Session,
    run: IngestionRun,
    chain: str,
    previous: dict[str, int],
    current: dict[str, int],
    sinks: Sequence[AlertSink],
    settings: Settings,
    now: datetime,
) -> AlertAction:
    compared = set(previous) & set(current)
    threshold = settings.INGEST_RECORD_DROP_PCT
    prev = sum(previous[key] for key in compared)
    cur = sum(current[key] for key in compared)
    drop_pct = _pct(prev - cur, prev) if prev > 0 else 0.0

    def dropped(key: str) -> bool:
        return previous[key] > 0 and _pct(previous[key] - current[key], previous[key]) > threshold

    def details(alert: IngestionAlert | None) -> dict[str, Any]:
        old = set(alert.details.get("series_keys", [])) if alert is not None else set()
        return {
            "prev": prev,
            "cur": cur,
            "pct": round(drop_pct, 1),
            "series": len(compared),
            "threshold": threshold,
            # Every series the open alert is about: it is resolved only by a run measuring them.
            "series_keys": sorted(old | compared),
        }

    def may_resolve(alert: IngestionAlert) -> bool:
        keys = set(alert.details.get("series_keys", []))
        if not keys or keys <= compared:
            return True
        measured = keys & compared
        return bool(measured) and not any(dropped(key) for key in measured)

    return _raise_or_resolve(
        session,
        chain_id=run.chain_id,
        chain=chain,
        kind="record_drop",
        holds=prev > 0 and drop_pct > threshold,
        details=details,
        run_id=run.id,
        sinks=sinks,
        settings=settings,
        now=now,
        may_resolve=may_resolve,
    )


def evaluate_run(
    session: Session,
    run_id: uuid.UUID,
    sinks: Sequence[AlertSink],
    settings: Settings,
    now: datetime,
) -> dict[AlertKind, AlertAction]:
    """record_drop and file_errors for a finished run. Commits each one on its own."""
    run = repository.get_run(session, run_id)
    if run is None:
        return {}
    chain = _chain_names(session).get(run.chain_id, str(run.chain_id))
    current = repository.run_series_records(session, run_id)
    previous = repository.previous_series_records(
        session, run.chain_id, run_id, current.keys(), until=run.started_at
    )
    session.commit()
    actions: dict[AlertKind, AlertAction] = {}

    if run.files_ingested + run.files_failed > 0 or run.status == "failed":
        action = _guarded(
            session,
            chain,
            "file_errors",
            lambda: _file_errors(session, run, chain, sinks, settings, now),
        )
        if action is not None:
            actions["file_errors"] = action

    if set(previous) & set(current):
        action = _guarded(
            session,
            chain,
            "record_drop",
            lambda: _record_drop(session, run, chain, previous, current, sinks, settings, now),
        )
        if action is not None:
            actions["record_drop"] = action
    return actions


def check_stale(
    session: Session,
    sinks: Sequence[AlertSink],
    settings: Settings,
    now: datetime,
    gov_chain_codes: Collection[str],
) -> dict[uuid.UUID, AlertAction]:
    """stale for every chain among gov_chain_codes (the configured ones) that has run at least
    once. Commits each chain on its own; a chain whose check fails is logged and left out."""
    names = {c.id: c.name for c in catalog_service.chains_by_gov_codes(session, gov_chain_codes)}
    limit = timedelta(hours=settings.INGEST_STALE_HOURS)
    actions: dict[uuid.UUID, AlertAction] = {}
    for chain_id, first_started, last_ok in repository.chain_activity(session, names.keys()):
        since = last_ok if last_ok is not None else first_started
        chain = names[chain_id]

        def check(
            chain_id: uuid.UUID = chain_id,
            chain: str = chain,
            since: datetime = since,
            last_ok: datetime | None = last_ok,
        ) -> AlertAction:
            return _raise_or_resolve(
                session,
                chain_id=chain_id,
                chain=chain,
                kind="stale",
                holds=now - since > limit,
                details={
                    "hours": round((now - since).total_seconds() / 3600, 1),
                    "threshold": settings.INGEST_STALE_HOURS,
                    "last_success_at": last_ok.isoformat() if last_ok is not None else None,
                },
                run_id=None,
                sinks=sinks,
                settings=settings,
                now=now,
            )

        action = _guarded(session, chain, "stale", check)
        if action is not None:
            actions[chain_id] = action
    return actions


def remind_open(
    session: Session,
    sinks: Sequence[AlertSink],
    settings: Settings,
    now: datetime,
) -> int:
    """Sends again every open record_drop and file_errors alert not sent for
    INGEST_ALERT_REPEAT_HOURS (or never sent), without measuring anything again: only a run
    measures them. stale is left to check_stale. Returns how many were sent."""
    due = now - timedelta(hours=settings.INGEST_ALERT_REPEAT_HOURS)
    names = _chain_names(session)
    alerts = repository.open_alerts_due(session, ("record_drop", "file_errors"), due)
    reminded = 0
    for alert in alerts:
        chain = names.get(alert.chain_id, str(alert.chain_id))

        def remind(alert: IngestionAlert = alert, chain: str = chain) -> AlertAction:
            _deliver(session, alert, chain, sinks, now)
            return "sent_again"

        if _guarded(session, chain, alert.kind, remind) is not None:
            reminded += 1
    session.commit()
    return reminded
