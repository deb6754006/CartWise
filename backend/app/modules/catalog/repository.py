"""catalog: data access. Only this module's repository touches its tables."""

import uuid
from collections.abc import Collection, Sequence

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.modules.catalog.models import Brand, Chain, Club


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


def ensure_chain_by_code(session: Session, gov_chain_code: str, name: str) -> uuid.UUID:
    """The chain with this government code, inserted (with name) if missing. Safe against a
    concurrent insert of the same code: gov_chain_code is unique."""
    session.execute(
        insert(Chain)
        .values(id=new_id(), name=name, gov_chain_code=gov_chain_code)
        .on_conflict_do_nothing(index_elements=[Chain.gov_chain_code])
    )
    return session.execute(
        select(Chain.id).where(Chain.gov_chain_code == gov_chain_code)
    ).scalar_one()


def ensure_club(session: Session, chain_id: uuid.UUID, name: str) -> uuid.UUID:
    session.execute(
        insert(Club)
        .values(id=new_id(), chain_id=chain_id, name=name)
        .on_conflict_do_nothing(index_elements=[Club.chain_id, Club.name])
    )
    return session.execute(
        select(Club.id).where(Club.chain_id == chain_id, Club.name == name)
    ).scalar_one()


def search_brands(session: Session, normalized: str, limit: int) -> Sequence[tuple[uuid.UUID, str]]:
    """Brands whose name_norm contains normalized, as literal text. Those that start with it
    come first, and then by name."""
    escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    stmt = (
        select(Brand.id, Brand.name)
        .where(Brand.name_norm.like(f"%{escaped}%", escape="\\"))
        .order_by(
            case((Brand.name_norm.like(f"{escaped}%", escape="\\"), 0), else_=1),
            Brand.name,
            Brand.id,
        )
        .limit(limit)
    )
    return [(row[0], row[1]) for row in session.execute(stmt).all()]


def brands_by_ids(session: Session, ids: Collection[uuid.UUID]) -> Sequence[tuple[uuid.UUID, str]]:
    if not ids:
        return []
    stmt = select(Brand.id, Brand.name).where(Brand.id.in_(ids)).order_by(Brand.name, Brand.id)
    return [(row[0], row[1]) for row in session.execute(stmt).all()]


def existing_brand_ids(session: Session, ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    return set(session.execute(select(Brand.id).where(Brand.id.in_(ids))).scalars())


def ensure_brand(session: Session, name: str, name_norm: str) -> uuid.UUID:
    session.execute(
        insert(Brand)
        .values(id=new_id(), name=name, name_norm=name_norm)
        .on_conflict_do_nothing(index_elements=[Brand.name])
    )
    return session.execute(select(Brand.id).where(Brand.name == name)).scalar_one()
