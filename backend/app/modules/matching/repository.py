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


def candidates_for_aliases(
    session: Session, alias_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[uuid.UUID, Decimal]]]:
    """alias_id -> its kept candidates (product_id, score), by rank."""
    found: dict[uuid.UUID, list[tuple[uuid.UUID, Decimal]]] = {}
    for start in range(0, len(alias_ids), 1000):
        batch = alias_ids[start : start + 1000]
        stmt = (
            select(MatchCandidate.alias_id, MatchCandidate.product_id, MatchCandidate.score)
            .where(MatchCandidate.alias_id.in_(batch))
            .order_by(MatchCandidate.alias_id, MatchCandidate.rank)
        )
        for alias_id, product_id, score in session.execute(stmt).all():
            found.setdefault(alias_id, []).append((product_id, score))
    return found


def aliases_with_candidate(session: Session, product_id: uuid.UUID) -> list[uuid.UUID]:
    """The aliases that have this product among their kept candidates, sorted."""
    stmt = select(MatchCandidate.alias_id).distinct().where(MatchCandidate.product_id == product_id)
    return sorted(session.execute(stmt).scalars().all())


def reassign_votes(
    session: Session, from_product: uuid.UUID, to_product: uuid.UUID
) -> list[uuid.UUID]:
    """Votes for from_product are for to_product. A vote is keyed by (alias_id, user_id), not by
    its product, so none collide. Returns the aliases of the votes moved, sorted (with repeats
    removed)."""
    stmt = (
        update(MatchVote)
        .where(MatchVote.product_id == from_product)
        .values(product_id=to_product)
        .returning(MatchVote.alias_id)
    )
    return sorted(set(session.execute(stmt).scalars().all()))


def others_to_confirm(
    session: Session, alias_id: uuid.UUID, product_id: uuid.UUID, now: datetime
) -> int:
    """The alias's other votes for product_id (its own product) become confirm. Returns how
    many."""
    result = session.execute(
        update(MatchVote)
        .where(
            MatchVote.alias_id == alias_id,
            MatchVote.vote == "other",
            MatchVote.product_id == product_id,
        )
        .values(vote="confirm", product_id=None, updated_at=now)
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


def user_votes_for_aliases(
    session: Session, alias_ids: Sequence[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID, str, uuid.UUID | None]]:
    """(alias_id, user_id, vote, product_id) of each vote with role user on these aliases, in one
    query."""
    if not alias_ids:
        return []
    stmt = select(
        MatchVote.alias_id, MatchVote.user_id, MatchVote.vote, MatchVote.product_id
    ).where(MatchVote.alias_id.in_(list(alias_ids)), MatchVote.role == "user")
    return [(r[0], r[1], r[2], r[3]) for r in session.execute(stmt).all()]
