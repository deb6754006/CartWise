"""matching: data access. Only this module's repository touches its tables."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.modules.matching.models import (
    VOTE_KEY_CONSTRAINT,
    MatchCandidate,
    MatchVote,
    VoteKind,
    VoteRole,
)


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


def upsert_vote(
    session: Session,
    alias_id: uuid.UUID,
    user_id: uuid.UUID,
    vote: VoteKind,
    product_id: uuid.UUID | None,
    role: VoteRole,
    now: datetime,
) -> None:
    """The user's vote on the alias: inserted, or replacing the one the user cast before. A
    vote with role user does not replace one with role operator."""
    stmt = insert(MatchVote).values(
        id=new_id(),
        alias_id=alias_id,
        user_id=user_id,
        product_id=product_id,
        vote=vote,
        role=role,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        constraint=VOTE_KEY_CONSTRAINT,
        set_={
            "product_id": stmt.excluded.product_id,
            "vote": stmt.excluded.vote,
            "role": stmt.excluded.role,
            "updated_at": stmt.excluded.updated_at,
        },
        # A user's vote never replaces the same person's approval as an operator.
        where=(MatchVote.role == "user") if role == "user" else None,
    )
    session.execute(stmt)


def alias_has_votes(session: Session, alias_id: uuid.UUID) -> bool:
    stmt = select(MatchVote.id).where(MatchVote.alias_id == alias_id).limit(1)
    return session.execute(stmt).first() is not None


def aliases_with_votes(session: Session, alias_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
    """Those of these aliases that have at least one vote."""
    found: set[uuid.UUID] = set()
    for start in range(0, len(alias_ids), 1000):
        batch = alias_ids[start : start + 1000]
        stmt = select(MatchVote.alias_id).distinct().where(MatchVote.alias_id.in_(batch))
        found.update(session.execute(stmt).scalars().all())
    return found


def user_votes(
    session: Session, alias_id: uuid.UUID
) -> Sequence[tuple[uuid.UUID, str, uuid.UUID | None]]:
    """(user_id, vote, product_id) of each vote on the alias with role user."""
    stmt = select(MatchVote.user_id, MatchVote.vote, MatchVote.product_id).where(
        MatchVote.alias_id == alias_id, MatchVote.role == "user"
    )
    return [(r[0], r[1], r[2]) for r in session.execute(stmt).all()]


def confirms_to_other(
    session: Session, alias_id: uuid.UUID, product_id: uuid.UUID | None, now: datetime
) -> None:
    """The alias's confirm votes become votes for product_id (the product they confirmed), as
    other; with no product, unknown."""
    values: dict[str, object] = (
        {"vote": "other", "product_id": product_id}
        if product_id is not None
        else {"vote": "unknown", "product_id": None}
    )
    session.execute(
        update(MatchVote)
        .where(MatchVote.alias_id == alias_id, MatchVote.vote == "confirm")
        .values(**values, updated_at=now)
    )


def delete_user_votes(session: Session, user_id: uuid.UUID) -> None:
    session.execute(delete(MatchVote).where(MatchVote.user_id == user_id))
