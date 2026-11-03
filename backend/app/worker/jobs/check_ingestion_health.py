"""Hourly job (Story 3.5): alerts the operator about a configured chain not ingested for
INGEST_STALE_HOURS, and reminds of every open alert not sent for INGEST_ALERT_REPEAT_HOURS.

Run by hand, from backend/: python -m app.worker.jobs.check_ingestion_health
"""

import logging
import sys
import uuid
from collections.abc import Callable, Collection, Sequence
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging
from app.modules.ingestion.adapters import (
    CARREFOUR_GOV_CODE,
    RAMI_LEVY_GOV_CODE,
    SHUFERSAL_GOV_CODE,
)
from app.modules.ingestion.alerts import AlertSink, build_alert_sinks
from app.modules.ingestion.health import AlertAction, check_stale, remind_open

logger = logging.getLogger("app.worker.check_ingestion_health")

# The chains the worker ingests (build_adapters): a chain no longer ingested is not alerted on.
CONFIGURED_GOV_CODES = (SHUFERSAL_GOV_CODE, RAMI_LEVY_GOV_CODE, CARREFOUR_GOV_CODE)


def run(
    session_factory: Callable[[], Session] = SessionLocal,
    sinks: Sequence[AlertSink] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    gov_chain_codes: Collection[str] = CONFIGURED_GOV_CODES,
) -> dict[uuid.UUID, AlertAction] | None:
    """One check: the stale action of each chain. Each chain and each alert is committed on its
    own. Never raises, so the scheduler keeps going: a crash is logged and gives None."""
    try:
        settings = get_settings()
        chosen = sinks if sinks is not None else build_alert_sinks(settings)
        at = now()
        with session_factory() as session:
            actions = check_stale(session, chosen, settings, at, gov_chain_codes)
            reminded = remind_open(session, chosen, settings, at)
    except Exception as exc:
        logger.error("check_ingestion_health_crashed", extra={"error": type(exc).__name__})
        return None
    stale = sum(1 for action in actions.values() if action in ("opened", "sent_again", "held"))
    logger.info(
        "check_ingestion_health_done",
        extra={"chains": len(actions), "stale": stale, "reminded": reminded},
    )
    return actions


def main(argv: list[str]) -> int:
    configure_logging(get_settings().LOG_LEVEL)
    if argv:
        print("usage: python -m app.worker.jobs.check_ingestion_health")
        return 2
    actions = run()
    if actions is None:
        return 1
    for chain_id, action in actions.items():
        print(f"{chain_id} stale: {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
