"""pricing: data access. Only this module's repository touches its tables."""

import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Text, Uuid, and_, bindparam, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY, distinct_on, insert
from sqlalchemy.orm import Session

from app.modules.pricing.models import (
    ObservationSource,
    PriceObservation,
    PriceType,
    Promotion,
    PromotionProduct,
)

# Rows per statement: well under Postgres's 65535 parameters.
BATCH = 1000


def latest_valid_observations(
    session: Session, store_id: uuid.UUID, source: ObservationSource, price_type: PriceType
) -> dict[uuid.UUID, tuple[int, str, datetime]]:
    """For each product of the store: (unit_price_agorot, per, observed_at) of its latest valid
    observation of this source and price type. One query."""
    stmt = (
        select(
            PriceObservation.product_id,
            PriceObservation.unit_price_agorot,
            PriceObservation.per,
            PriceObservation.observed_at,
        )
        .where(
            PriceObservation.store_id == store_id,
            PriceObservation.source == source,
            PriceObservation.price_type == price_type,
            PriceObservation.status == "valid",
        )
        .ext(distinct_on(PriceObservation.product_id))
        .order_by(
            PriceObservation.product_id,
            PriceObservation.observed_at.desc(),
            PriceObservation.id.desc(),
        )
    )
    return {row[0]: (row[1], row[2], row[3]) for row in session.execute(stmt).all()}


def insert_observations(session: Session, rows: Sequence[Mapping[str, Any]]) -> None:
    for start in range(0, len(rows), BATCH):
        session.execute(insert(PriceObservation), list(rows[start : start + BATCH]))


def upsert_promotions(session: Session, rows: Sequence[Mapping[str, Any]]) -> dict[str, uuid.UUID]:
    """Insert or update the store's promotions, keyed by (store_id, gov_promotion_id). Returns
    the id of each gov_promotion_id."""
    ids: dict[str, uuid.UUID] = {}
    for start in range(0, len(rows), BATCH):
        values = insert(Promotion).values(list(rows[start : start + BATCH]))
        excluded = values.excluded
        stmt = values.on_conflict_do_update(
            index_elements=[Promotion.store_id, Promotion.gov_promotion_id],
            set_={
                "chain_id": excluded.chain_id,
                "description": excluded.description,
                "club_id": excluded.club_id,
                "kind": excluded.kind,
                "min_qty": excluded.min_qty,
                "bundle_price_agorot": excluded.bundle_price_agorot,
                "percent": excluded.percent,
                "starts_at": excluded.starts_at,
                "ends_at": excluded.ends_at,
                "source": excluded.source,
                "updated_at": excluded.updated_at,
            },
        ).returning(Promotion.gov_promotion_id, Promotion.id)
        for gov_id, promotion_id in session.execute(stmt).all():
            ids[gov_id] = promotion_id
    return ids


def replace_promotion_products(
    session: Session, products: Mapping[uuid.UUID, Collection[uuid.UUID]]
) -> None:
    """Each promotion's products become exactly these."""
    promotion_ids = list(products)
    for start in range(0, len(promotion_ids), BATCH):
        batch = promotion_ids[start : start + BATCH]
        session.execute(delete(PromotionProduct).where(PromotionProduct.promotion_id.in_(batch)))
    pairs = [
        {"promotion_id": promotion_id, "product_id": product_id}
        for promotion_id, product_ids in products.items()
        for product_id in sorted(product_ids)
    ]
    for start in range(0, len(pairs), BATCH):
        session.execute(insert(PromotionProduct), pairs[start : start + BATCH])


def end_promotions_not_in(
    session: Session, store_id: uuid.UUID, keep: Collection[str], at: datetime
) -> int:
    """The store's promotions not yet ended at `at`, other than those in keep, end at `at` (or at
    their start, for one that has not started). Returns how many."""
    stmt = (
        update(Promotion)
        .where(
            Promotion.store_id == store_id,
            Promotion.ends_at > at,
            Promotion.gov_promotion_id
            != func.all(bindparam("keep", list(keep), type_=ARRAY(Text()))),
        )
        .values(ends_at=func.greatest(Promotion.starts_at, at), updated_at=at)
    )
    return int(session.execute(stmt).rowcount)  # type: ignore[attr-defined]


def active_promotions(
    session: Session, store_ids: Collection[uuid.UUID], at: datetime
) -> list[tuple[Promotion, list[uuid.UUID]]]:
    if not store_ids:
        return []
    promotions = (
        session.execute(
            select(Promotion)
            .where(
                Promotion.store_id.in_(list(store_ids)),
                and_(Promotion.starts_at <= at, Promotion.ends_at > at),
            )
            .order_by(Promotion.store_id, Promotion.gov_promotion_id, Promotion.id)
        )
        .scalars()
        .all()
    )
    products: dict[uuid.UUID, list[uuid.UUID]] = {p.id: [] for p in promotions}
    ids = list(products)
    for start in range(0, len(ids), BATCH):
        stmt = (
            select(PromotionProduct.promotion_id, PromotionProduct.product_id)
            .where(PromotionProduct.promotion_id.in_(ids[start : start + BATCH]))
            .order_by(PromotionProduct.promotion_id, PromotionProduct.product_id)
        )
        for promotion_id, product_id in session.execute(stmt).all():
            products[promotion_id].append(product_id)
    return [(p, products[p.id]) for p in promotions]


def refresh_current_prices(session: Session) -> None:
    # CONCURRENTLY: readers of the view are not blocked while it refreshes (it has a unique
    # index, ux_current_prices).
    session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY current_prices"))


def current_prices(
    session: Session, store_id: uuid.UUID, price_type: PriceType
) -> dict[uuid.UUID, tuple[int, str, datetime, uuid.UUID]]:
    """product_id -> (unit_price_agorot, per, observed_at, observation_id), from the view."""
    stmt = text(
        "SELECT product_id, unit_price_agorot, per, observed_at, observation_id "
        "FROM current_prices WHERE store_id = :store_id AND price_type = :price_type"
    )
    rows = session.execute(stmt, {"store_id": store_id, "price_type": price_type}).all()
    return {row[0]: (row[1], row[2], row[3], row[4]) for row in rows}


def median_prices(
    session: Session, product_ids: Sequence[uuid.UUID], price_type: PriceType
) -> dict[uuid.UUID, float]:
    """product_id -> the median unit_price_agorot of its current prices of this type per unit, in
    all stores, from the view. Prices per kg are left out (a weighted product has none), and so
    is a product with no price."""
    stmt = text(
        "SELECT product_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY unit_price_agorot) "
        "FROM current_prices WHERE price_type = :price_type AND per = 'unit' "
        "AND product_id = ANY(:ids) "
        "GROUP BY product_id"
    ).bindparams(bindparam("ids", type_=ARRAY(Uuid())))
    found: dict[uuid.UUID, float] = {}
    for start in range(0, len(product_ids), BATCH):
        params = {"ids": list(product_ids[start : start + BATCH]), "price_type": price_type}
        for product_id, median in session.execute(stmt, params).all():
            found[product_id] = float(median)
    return found
