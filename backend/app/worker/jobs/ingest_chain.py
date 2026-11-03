"""Scheduled job: one ingestion run of one chain's official price files (Story 3.2).

Run by hand, from backend/: python -m app.worker.jobs.ingest_chain shufersal
"""

import logging
import sys
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging
from app.modules.geo.service import Geocoder, worker_geocoder
from app.modules.ingestion.adapters import CHAIN_KEYS, ChainAdapter, build_adapters
from app.modules.ingestion.service import RunSummary, handlers_with_geocoder, ingest_chain

logger = logging.getLogger("app.worker.ingest_chain")


def run(
    chain_key: str,
    session_factory: Callable[[], Session] = SessionLocal,
    adapters: Callable[[], dict[str, ChainAdapter]] | None = None,
    geocoder: Geocoder | None = None,
) -> RunSummary | None:
    """One run. Never raises, so the scheduler keeps going: a crash is logged and gives None.

    The adapters are built anew for each run, so each one starts with a fresh cookie jar.
    Stores are geocoded with geocoder, by default the worker's Nominatim geocoder (no wait limit).
    """
    try:
        settings = get_settings()
        built = adapters() if adapters is not None else build_adapters(settings)
        adapter = built.get(chain_key)
        if adapter is None:
            logger.error("ingest_chain_unknown", extra={"chain": chain_key})
            return None
        handlers = handlers_with_geocoder(
            geocoder if geocoder is not None else worker_geocoder(settings)
        )
        return ingest_chain(session_factory, adapter, handlers)
    except Exception as exc:
        logger.error(
            "ingest_chain_crashed", extra={"chain": chain_key, "error": type(exc).__name__}
        )
        return None


def main(argv: list[str]) -> int:
    configure_logging(get_settings().LOG_LEVEL)
    if len(argv) != 1 or argv[0] not in CHAIN_KEYS:
        print(f"usage: python -m app.worker.jobs.ingest_chain {{{'|'.join(CHAIN_KEYS)}}}")
        return 2
    summary = run(argv[0])
    print(summary)
    return 0 if summary is not None and summary.status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
