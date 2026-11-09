"""catalog: data access. Only this module's repository touches its tables."""

import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    Text,
    and_,
    case,
    cast,
    func,
    literal,
    literal_column,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.modules.catalog.models import (
    ALIAS_KEY_CONSTRAINT,
    Brand,
    Chain,
    Club,
    Geography,
    Product,
    ProductAlias,
    Store,
)


def list_chains(session: Session) -> Sequence[tuple[uuid.UUID, str]]:
    rows = session.execute(select(Chain.id, Chain.name).order_by(Chain.name, Chain.id)).all()
    return [(row[0], row[1]) for row in rows]


def chains_by_gov_codes(
    session: Session, gov_chain_codes: Collection[str]
) -> Sequence[tuple[uuid.UUID, str]]:
    if not gov_chain_codes:
        return []
    stmt = select(Chain.id, Chain.name).where(Chain.gov_chain_code.in_(list(gov_chain_codes)))
    return [(row[0], row[1]) for row in session.execute(stmt.order_by(Chain.id)).all()]


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


# id, status, has_location, location_source, geocoded_query, geocode_attempted_at
_STORE_STATE = (
    Store.id,
    Store.status,
    Store.location.is_not(None).label("has_location"),
    Store.location_source,
    Store.geocoded_query,
    Store.geocode_attempted_at,
)


def _point(lat: float, lng: float) -> Any:
    return cast(func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326), Geography())


# A row of _STORE_STATE, by attribute (row.id, row.has_location, ...).
type StoreStateRow = Any


def upsert_store(
    session: Session,
    *,
    chain_id: uuid.UUID,
    gov_store_code: str,
    sub_chain_code: str | None,
    name: str,
    name_norm: str,
    address: str,
    city_code: str | None,
    zip_code: str | None,
    store_type: int | None,
    online: bool,
    now: datetime,
) -> StoreStateRow:
    """Insert the store, or update its details from the file. Its location is left as it is.

    The status follows the store: online for an online store, and for a physical one active when
    it has a location and needs_location when it has none.
    """
    details = {
        "sub_chain_code": sub_chain_code,
        "name": name,
        "name_norm": name_norm,
        "address": address,
        "city_code": city_code,
        "zip_code": zip_code,
        "store_type": store_type,
        "last_seen_at": now,
        "updated_at": now,
    }
    insert_stmt = insert(Store).values(
        id=new_id(),
        chain_id=chain_id,
        gov_store_code=gov_store_code,
        status="online" if online else "needs_location",
        created_at=now,
        **details,
    )
    status: Any = (
        "online"
        if online
        else case((Store.location.is_not(None), "active"), else_="needs_location")
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[Store.chain_id, Store.gov_store_code],
        set_={**details, "status": status},
    ).returning(*_STORE_STATE)
    return session.execute(stmt).one()


def set_store_geocoded(
    session: Session, store_id: uuid.UUID, query: str, lat: float, lng: float, now: datetime
) -> None:
    session.execute(
        update(Store)
        .where(Store.id == store_id, Store.location_source.is_distinct_from("manual"))
        .values(
            location=_point(lat, lng),
            location_source="geocoded",
            geocoded_query=query,
            geocode_attempted_at=None,
            status="active",
            updated_at=now,
        )
    )


def set_store_geocode_failed(
    session: Session, store_id: uuid.UUID, query: str, now: datetime
) -> None:
    """A location the store already has is kept, and so is its status."""
    session.execute(
        update(Store)
        .where(Store.id == store_id, Store.location_source.is_distinct_from("manual"))
        .values(
            geocoded_query=query,
            geocode_attempted_at=now,
            status=case((Store.location.is_not(None), Store.status), else_="needs_location"),
            updated_at=now,
        )
    )


def set_store_location_manual(
    session: Session, store_id: uuid.UUID, lat: float, lng: float, now: datetime
) -> Literal["set", "missing", "online"]:
    """An online store is not changed."""
    status = session.execute(
        select(Store.status).where(Store.id == store_id).with_for_update()
    ).scalar_one_or_none()
    if status is None:
        return "missing"
    if status == "online":
        return "online"
    session.execute(
        update(Store)
        .where(Store.id == store_id)
        .values(
            location=_point(lat, lng),
            location_source="manual",
            status="active",
            updated_at=now,
        )
    )
    return "set"


def stores_needing_location(
    session: Session,
) -> Sequence[tuple[uuid.UUID, uuid.UUID, str, str, str, str, str | None]]:
    stmt = (
        select(
            Store.id,
            Store.chain_id,
            Chain.name,
            Store.gov_store_code,
            Store.name,
            Store.address,
            Store.city_code,
        )
        .join(Chain, Store.chain_id == Chain.id)
        .where(Store.status == "needs_location")
        .order_by(Chain.name, Chain.id, func.length(Store.gov_store_code), Store.gov_store_code)
    )
    return [(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in session.execute(stmt).all()]


def comparable_store_ids(session: Session, chain_id: uuid.UUID | None) -> list[uuid.UUID]:
    stmt = select(Store.id).where(Store.status == "active", Store.location.is_not(None))
    if chain_id is not None:
        stmt = stmt.where(Store.chain_id == chain_id)
    return list(session.execute(stmt.order_by(Store.id)).scalars())


def chain_name(session: Session, chain_id: uuid.UUID) -> str:
    return session.execute(select(Chain.name).where(Chain.id == chain_id)).scalar_one()


def store_id_by_code(
    session: Session, chain_id: uuid.UUID, gov_store_code: str
) -> uuid.UUID | None:
    stmt = select(Store.id).where(
        Store.chain_id == chain_id, Store.gov_store_code == gov_store_code
    )
    return session.execute(stmt).scalar_one_or_none()


# Rows per statement: well under Postgres's 65535 parameters, at 9 columns a row.
PRODUCT_BATCH = 1000


def insert_products(session: Session, rows: Sequence[Mapping[str, Any]]) -> None:
    """Insert products, in batches. A barcode that already has a product is left as it is."""
    for start in range(0, len(rows), PRODUCT_BATCH):
        batch = rows[start : start + PRODUCT_BATCH]
        session.execute(
            insert(Product)
            .values(list(batch))
            .on_conflict_do_nothing(index_elements=[Product.barcode])
        )


def product_ids_by_barcode(session: Session, barcodes: Sequence[str]) -> dict[str, uuid.UUID]:
    found: dict[str, uuid.UUID] = {}
    for start in range(0, len(barcodes), PRODUCT_BATCH):
        batch = barcodes[start : start + PRODUCT_BATCH]
        stmt = select(Product.barcode, Product.id).where(Product.barcode.in_(batch))
        for barcode, product_id in session.execute(stmt).all():
            if barcode is not None:
                found[barcode] = product_id
    return found


# Rows per statement: well under Postgres's 65535 parameters, at 10 columns a row.
ALIAS_BATCH = 1000
# States a barcode match never changes: decided by votes or by an operator.
_SETTLED_STATES = ("final", "disputed")

_ALIAS_REF = (ProductAlias.id, ProductAlias.state, ProductAlias.product_id, ProductAlias.confidence)


def _certain_on_conflict(stmt: Any) -> Any:
    """On a key that exists: move the alias to the inserted product, as certain. A final or
    disputed alias is not changed, nor is one already certain for that product and confidence."""
    return stmt.on_conflict_do_update(
        constraint=ALIAS_KEY_CONSTRAINT,
        set_={
            "product_id": stmt.excluded.product_id,
            "state": "certain",
            "confidence": stmt.excluded.confidence,
            "updated_at": stmt.excluded.updated_at,
        },
        where=and_(
            ProductAlias.state.not_in(_SETTLED_STATES),
            or_(
                ProductAlias.state != "certain",
                ProductAlias.product_id.is_distinct_from(stmt.excluded.product_id),
                ProductAlias.confidence.is_distinct_from(stmt.excluded.confidence),
            ),
        ),
    )


def upsert_certain_alias(
    session: Session,
    *,
    chain_id: uuid.UUID,
    alias_text: str,
    alias_norm: str,
    barcode: str,
    product_id: uuid.UUID,
    confidence: Decimal,
    now: datetime,
) -> Any:
    """Insert the alias as certain for product_id, or move an existing one of the same key to it.
    A final or disputed alias is not changed, nor is one already certain for product_id. Returns
    the alias after that (id, state, product_id, confidence)."""
    stmt = insert(ProductAlias).values(
        id=new_id(),
        chain_id=chain_id,
        alias_text=alias_text,
        alias_norm=alias_norm,
        barcode=barcode,
        product_id=product_id,
        state="certain",
        confidence=confidence,
        created_at=now,
        updated_at=now,
    )
    stmt = _certain_on_conflict(stmt)
    row = session.execute(stmt.returning(*_ALIAS_REF)).one_or_none()
    if row is not None:
        return row
    # The alias exists and was left as it is.
    return session.execute(
        select(*_ALIAS_REF).where(
            ProductAlias.chain_id == chain_id,
            ProductAlias.alias_norm == alias_norm,
            ProductAlias.barcode == barcode,
        )
    ).one()


def upsert_certain_aliases(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    """Insert certain aliases, in batches (keys unique within rows). One whose key exists is moved
    to the row's product, as in upsert_certain_alias. Returns how many were inserted."""
    inserted = 0
    for start in range(0, len(rows), ALIAS_BATCH):
        batch = rows[start : start + ALIAS_BATCH]
        stmt = _certain_on_conflict(insert(ProductAlias).values(list(batch)))
        # xmax is 0 for a row this statement inserted, and set for one it updated.
        flags = session.execute(stmt.returning(literal_column("xmax = 0"))).scalars().all()
        inserted += sum(1 for flag in flags if flag)
    return inserted


def _alias_key(chain_id: uuid.UUID, alias_norm: str, barcode: str | None) -> Any:
    # NULL is one barcode value in the key (NULLS NOT DISTINCT).
    return and_(
        ProductAlias.chain_id == chain_id,
        ProductAlias.alias_norm == alias_norm,
        ProductAlias.barcode.is_not_distinct_from(barcode),
    )


def alias_by_key(
    session: Session, chain_id: uuid.UUID, alias_norm: str, barcode: str | None
) -> Any:
    """(id, state, product_id, confidence) of the alias of this key, or None."""
    return session.execute(
        select(*_ALIAS_REF).where(_alias_key(chain_id, alias_norm, barcode))
    ).one_or_none()


def alias_products_by_norm(
    session: Session, chain_id: uuid.UUID, norms: Sequence[str]
) -> dict[str, uuid.UUID]:
    """alias_norm -> product_id, for the chain's no-barcode aliases among norms (in any alias
    state) that point to a product not merged into another."""
    found: dict[str, uuid.UUID] = {}
    for start in range(0, len(norms), ALIAS_BATCH):
        batch = norms[start : start + ALIAS_BATCH]
        stmt = (
            select(ProductAlias.alias_norm, Product.id)
            .join(Product, Product.id == ProductAlias.product_id)
            .where(
                ProductAlias.chain_id == chain_id,
                ProductAlias.barcode.is_(None),
                ProductAlias.alias_norm.in_(batch),
                Product.status != "merged_into",
            )
        )
        found.update((norm, product_id) for norm, product_id in session.execute(stmt).all())
    return found


def upsert_alias(
    session: Session,
    *,
    chain_id: uuid.UUID,
    alias_text: str,
    alias_norm: str,
    barcode: str | None,
    state: Literal["certain", "uncertain"],
    product_id: uuid.UUID,
    confidence: Decimal | None,
    now: datetime,
) -> Any:
    """Insert the alias, or set an existing one of the same key to this state, product and
    confidence. Not changed: a final or disputed alias, and a certain one for product_id when the
    new state is uncertain. Returns the alias after that (id, state, product_id, confidence)."""
    stmt = insert(ProductAlias).values(
        id=new_id(),
        chain_id=chain_id,
        alias_text=alias_text,
        alias_norm=alias_norm,
        barcode=barcode,
        product_id=product_id,
        state=state,
        confidence=confidence,
        created_at=now,
        updated_at=now,
    )
    excluded = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        constraint=ALIAS_KEY_CONSTRAINT,
        set_={
            "product_id": excluded.product_id,
            "state": excluded.state,
            "confidence": excluded.confidence,
            "updated_at": excluded.updated_at,
        },
        where=and_(
            ProductAlias.state.not_in(_SETTLED_STATES),
            # A certain alias does not go down to uncertain for the same product.
            or_(
                ProductAlias.state != "certain",
                excluded.state != "uncertain",
                ProductAlias.product_id.is_distinct_from(excluded.product_id),
            ),
            or_(
                ProductAlias.state != excluded.state,
                ProductAlias.product_id.is_distinct_from(excluded.product_id),
                ProductAlias.confidence.is_distinct_from(excluded.confidence),
            ),
        ),
    )
    row = session.execute(stmt.returning(*_ALIAS_REF)).one_or_none()
    if row is not None:
        return row
    # The alias exists and was left as it is.
    return session.execute(
        select(*_ALIAS_REF).where(_alias_key(chain_id, alias_norm, barcode))
    ).one()


def insert_product(session: Session, row: Mapping[str, Any]) -> uuid.UUID:
    """Insert one product and return its id. When its barcode already has a product (another
    transaction created it), nothing is inserted and that product's id is returned."""
    inserted = session.execute(
        insert(Product)
        .values(**row)
        .on_conflict_do_nothing(index_elements=[Product.barcode])
        .returning(Product.id)
    ).scalar_one_or_none()
    if inserted is not None:
        return inserted
    return session.execute(select(Product.id).where(Product.barcode == row["barcode"])).scalar_one()


def product_statuses(session: Session, ids: Collection[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    stmt = select(Product.id, Product.status).where(Product.id.in_(list(ids)))
    return {row[0]: row[1] for row in session.execute(stmt).all()}


def product_candidates(
    session: Session, alias_norm: str, threshold: float, limit: int
) -> Sequence[tuple[uuid.UUID, str, Decimal | None, str | None, str, float]]:
    """Up to limit products whose name_norm is trigram-similar to alias_norm (at least
    threshold), most similar first: (id, name_norm, pack_size, pack_unit, status, similarity). A
    product merged into another is not one."""
    setting = "pg_trgm.similarity_threshold"
    # None until pg_trgm is loaded in this connection: restoring it then resets the default.
    previous = session.execute(select(func.current_setting(setting, True))).scalar_one()
    # % uses the trigram index, with this threshold; restored after the query.
    session.execute(select(func.set_config(setting, str(threshold), True)))
    similarity = func.similarity(Product.name_norm, alias_norm)
    stmt = (
        select(
            Product.id,
            Product.name_norm,
            Product.pack_size,
            Product.pack_unit,
            Product.status,
            similarity,
        )
        .where(Product.name_norm.op("%")(alias_norm), Product.status != "merged_into")
        .order_by(similarity.desc(), Product.id)
        .limit(limit)
    )
    try:
        rows = session.execute(stmt).all()
    finally:
        session.execute(select(func.set_config(setting, literal(previous, Text), True)))
    return [(r[0], r[1], r[2], r[3], r[4], float(r[5])) for r in rows]


def sample_certain_barcode_aliases(
    session: Session, limit: int, seed: str
) -> Sequence[tuple[uuid.UUID, str, uuid.UUID, str]]:
    """Up to limit certain aliases with a barcode and a product: (id, alias_norm, product_id,
    the product's name_norm). The same seed picks the same aliases, while they exist."""
    stmt = (
        select(ProductAlias.id, ProductAlias.alias_norm, Product.id, Product.name_norm)
        .join(Product, Product.id == ProductAlias.product_id)
        .where(ProductAlias.state == "certain", ProductAlias.barcode.is_not(None))
        .order_by(func.md5(func.concat(seed, cast(ProductAlias.id, Text))), ProductAlias.id)
        .limit(limit)
    )
    return [(r[0], r[1], r[2], r[3]) for r in session.execute(stmt).all()]
