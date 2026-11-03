"""Stores with no location (Story 3.3): list them, and set a location by hand.

Run from backend/ (or in the api container: docker compose exec api python -m ...):
  uv run python -m scripts.store_locations list
  uv run python -m scripts.store_locations set <store_id> <lat> <lng>

A store without a location is left out of comparisons. A location set here is never replaced by
geocoding. Refuses to run when the database cannot be reached.
"""

import io
import sys
import uuid
from collections.abc import Callable, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import make_engine
from app.modules.catalog import service as catalog_service

USAGE = (
    "usage: python -m scripts.store_locations list\n"
    "       python -m scripts.store_locations set <store_id> <lat> <lng>"
)


def list_stores(session: Session) -> list[str]:
    """One tab-separated line per store: id, chain, store code, name, address, city code."""
    return [
        "\t".join(
            (
                str(store.id),
                store.chain_name,
                store.gov_store_code,
                store.name,
                store.address,
                store.city_code or "",
            )
        )
        for store in catalog_service.stores_needing_location(session)
    ]


def set_location(session: Session, store_id: str, lat: str, lng: str) -> None:
    """Raises ValueError, changing nothing, for a bad id, bad coordinates or an unknown store."""
    catalog_service.set_store_location_manual(session, uuid.UUID(store_id), float(lat), float(lng))
    session.commit()


def run(argv: Sequence[str], session_factory: Callable[[], Session]) -> int:
    if argv[:1] == ["list"] and len(argv) == 1:
        with session_factory() as session:
            lines = list_stores(session)
        for line in lines:
            print(line)
        print(f"store_locations: {len(lines)} stores need a location", file=sys.stderr)
        return 0
    if argv[:1] == ["set"] and len(argv) == 4:
        try:
            with session_factory() as session:
                set_location(session, argv[1], argv[2], argv[3])
        except ValueError as exc:
            print(f"store_locations: {exc}", file=sys.stderr)
            return 1
        print(f"store_locations: store {argv[1]} is located by hand")
        return 0
    print(USAGE, file=sys.stderr)
    return 2


def main(argv: Sequence[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")  # names and addresses are in Hebrew
    engine = make_engine(get_settings().DATABASE_URL)
    try:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            print(
                f"store_locations: no database ({type(exc).__name__}); set DATABASE_URL",
                file=sys.stderr,
            )
            return 1
        return run(argv, lambda: Session(engine))
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
