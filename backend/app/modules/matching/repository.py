"""matching: data access. Only this module's repository touches its tables."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.matching.models import MatchCandidate


def replace_candidates(
    session: Session,
    alias_id: uuid.UUID,
    candidates: Sequence[tuple[uuid.UUID, Decimal]],
    now: datetime,
) -> None:
    """The alias's candidates become exactly these (product_id, score), ranked in this order
    from 1. None: the alias has no candidates."""
    session.execute(delete(MatchCandidate).where(MatchCandidate.alias_id == alias_id))
    if not candidates:
        return
    stmt = insert(MatchCandidate).values(
        [
            {
                "alias_id": alias_id,
                "rank": rank,
                "product_id": product_id,
                "score": score,
                "created_at": now,
            }
            for rank, (product_id, score) in enumerate(candidates, start=1)
        ]
    )
    # Another match of the same alias, at the same time, may have inserted them: the last wins.
    stmt = stmt.on_conflict_do_update(
        index_elements=[MatchCandidate.alias_id, MatchCandidate.rank],
        set_={
            "product_id": stmt.excluded.product_id,
            "score": stmt.excluded.score,
            "created_at": stmt.excluded.created_at,
        },
    )
    session.execute(stmt)
