"""catalog: data access. Only this module's repository touches its tables."""

import uuid
from collections.abc import Collection, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.modules.catalog.models import Chain, Club


def list_chains(session: Session) -> Sequence[tuple[uuid.UUID, str]]:
    rows = session.execute(select(Chain.id, Chain.name).order_by(Chain.name, Chain.id)).all()
    return [(row[0], row[1]) for row in rows]


def list_clubs(session: Session) -> Sequence[tuple[uuid.UUID, str, uuid.UUID, str]]:
    stmt = (
        select(Club.id, Club.name, Club.chain_id, Chain.name)
        .join(Chain, Club.chain_id == Chain.id)
        .order_by(Chain.name, Chain.id, Club.name, Club.id)
    )
    return [(row[0], row[1], row[2], row[3]) for row in session.execute(stmt).all()]


def existing_club_ids(session: Session, ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    return set(session.execute(select(Club.id).where(Club.id.in_(ids))).scalars())


def ensure_chain(session: Session, name: str) -> uuid.UUID:
    """The chain with this name, inserted if missing. Chain names are not unique in the
    schema, so this is idempotent but not safe against a concurrent insert of the same name."""
    stmt = select(Chain.id).where(Chain.name == name).order_by(Chain.id).limit(1)
    chain_id = session.execute(stmt).scalar_one_or_none()
    if chain_id is not None:
        return chain_id
    chain_id = new_id()
    session.execute(insert(Chain).values(id=chain_id, name=name))
    return chain_id


def ensure_club(session: Session, chain_id: uuid.UUID, name: str) -> uuid.UUID:
    session.execute(
        insert(Club)
        .values(id=new_id(), chain_id=chain_id, name=name)
        .on_conflict_do_nothing(index_elements=[Club.chain_id, Club.name])
    )
    return session.execute(
        select(Club.id).where(Club.chain_id == chain_id, Club.name == name)
    ).scalar_one()
