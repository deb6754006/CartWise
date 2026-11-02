"""Fictional chains and clubs, so the clubs screen can be seen locally. Refuses to run in prod.

Run from backend/: uv run python -m scripts.seed_dev_catalog

Real chains are chosen in Story 3.1, with the owner's approval: never add their names here.
"""

import sys

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import make_engine
from app.modules.catalog import service as catalog_service

CHAINS = ("רשת א׳", "רשת ב׳", "רשת ג׳")


def seed(session: Session) -> None:
    """Idempotent: running it again changes nothing."""
    for chain in CHAINS:
        catalog_service.ensure_chain_with_club(session, chain, f"מועדון {chain}")
    session.commit()


def main() -> int:
    settings = get_settings()
    if settings.ENV == "prod":
        print("seed_dev_catalog: refusing to run with ENV=prod", file=sys.stderr)
        return 1
    engine = make_engine(settings.DATABASE_URL)
    try:
        with Session(engine) as session:
            seed(session)
    finally:
        engine.dispose()
    print(f"seed_dev_catalog: {len(CHAINS)} chains and clubs are in place")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
