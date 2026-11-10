"""pricing: business logic. Other modules use pricing data only through this file.

Prices are observations that never change (AD-3): a new one is written only when the price
changed, and the current price is the materialized view current_prices, refreshed after each
ingestion run. Promotions come from the chains' PromoFull files, one full picture per store.
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.modules.pricing import repository
from app.modules.pricing.models import PricePer, PriceType, PromotionKind


@dataclass(frozen=True, slots=True)
class OfficialPrice:
    """A regular price of a product, from a chain's price file."""

    product_id: uuid.UUID
    unit_price_agorot: int
    per: PricePer
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class PromotionRecord:
    """A promotion of a store, from the chain's PromoFull file, ready to be saved."""

    gov_promotion_id: str
    description: str
    club_id: uuid.UUID | None
    kind: PromotionKind
    min_qty: Decimal
    bundle_price_agorot: int | None
    percent: Decimal | None
    starts_at: datetime
    ends_at: datetime
    product_ids: frozenset[uuid.UUID]


@dataclass(frozen=True, slots=True)
class ActivePromotion:
    id: uuid.UUID
    store_id: uuid.UUID
    chain_id: uuid.UUID
    gov_promotion_id: str
    description: str
    club_id: uuid.UUID | None
    kind: PromotionKind
    min_qty: Decimal
    bundle_price_agorot: int | None
    percent: Decimal | None
    starts_at: datetime
    ends_at: datetime
    product_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class CurrentPrice:
    product_id: uuid.UUID
    unit_price_agorot: int
    per: PricePer
    observed_at: datetime
    observation_id: uuid.UUID


def record_official_prices(
    session: Session,
    store_id: uuid.UUID,
    chain_id: uuid.UUID,
    prices: Sequence[OfficialPrice],
    source_ref: str | None,
    at: datetime,
) -> tuple[int, int]:
    """Write a regular official_file observation for each price that differs (in agorot or per)
    from the product's latest valid one in the store, or that has none. Returns (new, unchanged).

    The first price of a product wins. An observation never goes back in time: one stamped
    before the product's latest is stamped at that time instead (the newer id breaks the tie),
    so it is the latest. Does not commit: the caller owns the transaction.
    """
    previous = repository.latest_valid_observations(session, store_id, "official_file", "regular")
    seen: set[uuid.UUID] = set()
    rows = []
    unchanged = 0
    for price in prices:
        if price.product_id in seen:
            continue
        seen.add(price.product_id)
        last = previous.get(price.product_id)
        observed_at = price.observed_at
        if last is not None:
            if (last[0], last[1]) == (price.unit_price_agorot, price.per):
                unchanged += 1
                continue
            observed_at = max(observed_at, last[2])
        rows.append(
            {
                "id": new_id(),
                "product_id": price.product_id,
                "store_id": store_id,
                "chain_id": chain_id,
                "source": "official_file",
                "price_type": "regular",
                "unit_price_agorot": price.unit_price_agorot,
                "per": price.per,
                "observed_at": observed_at,
                "source_ref": source_ref,
                "contributor_user_id": None,
                "status": "valid",
                "has_personal_discount": False,
                "created_at": at,
            }
        )
    repository.insert_observations(session, rows)
    return len(rows), unchanged


def replace_store_promotions(
    session: Session,
    store_id: uuid.UUID,
    chain_id: uuid.UUID,
    promos: Sequence[PromotionRecord],
    at: datetime,
) -> int:
    """Save the store's promotions from a full file: each is inserted or updated by
    (store_id, gov_promotion_id), with its products replaced. A promotion of the store that is not
    among them, and has not ended, ends at `at`. Returns how many were saved.

    The first promotion of an id wins. Does not commit: the caller owns the transaction.
    """
    first: dict[str, PromotionRecord] = {}
    for promo in promos:
        if promo.product_ids:
            first.setdefault(promo.gov_promotion_id, promo)
    rows = [
        {
            "id": new_id(),
            "chain_id": chain_id,
            "store_id": store_id,
            "gov_promotion_id": promo.gov_promotion_id,
            "description": promo.description,
            "club_id": promo.club_id,
            "kind": promo.kind,
            "min_qty": promo.min_qty,
            "bundle_price_agorot": promo.bundle_price_agorot,
            "percent": promo.percent,
            "starts_at": promo.starts_at,
            "ends_at": promo.ends_at,
            "source": "official_file",
            "updated_at": at,
        }
        for promo in first.values()
    ]
    ids = repository.upsert_promotions(session, rows)
    repository.replace_promotion_products(
        session, {ids[gov_id]: promo.product_ids for gov_id, promo in first.items()}
    )
    repository.end_promotions_not_in(session, store_id, list(first), at)
    return len(first)


def active_promotions(
    session: Session, store_ids: Collection[uuid.UUID], at: datetime
) -> list[ActivePromotion]:
    """The promotions of these stores in effect at `at` (starts_at <= at < ends_at), with their
    products. The entry point of Epic 5's effective price."""
    return [
        ActivePromotion(
            id=p.id,
            store_id=p.store_id,
            chain_id=p.chain_id,
            gov_promotion_id=p.gov_promotion_id,
            description=p.description,
            club_id=p.club_id,
            kind=p.kind,
            min_qty=p.min_qty,
            bundle_price_agorot=p.bundle_price_agorot,
            percent=p.percent,
            starts_at=p.starts_at,
            ends_at=p.ends_at,
            product_ids=tuple(product_ids),
        )
        for p, product_ids in repository.active_promotions(session, store_ids, at)
    ]


def current_prices(
    session: Session, store_id: uuid.UUID, price_type: PriceType = "regular"
) -> dict[uuid.UUID, CurrentPrice]:
    """The store's current prices of this type, by product, as of the last refresh."""
    return {
        product_id: CurrentPrice(product_id, row[0], row[1], row[2], row[3])  # type: ignore[arg-type]
        for product_id, row in repository.current_prices(session, store_id, price_type).items()
    }


def refresh_current_prices(session: Session) -> None:
    """Refresh current_prices. Does not commit: the caller owns the transaction."""
    repository.refresh_current_prices(session)


def median_prices(session: Session, product_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, int]:
    """The median of each product's current regular prices per unit, in agorot, in all stores, as
    of the last refresh. A product with no such price is left out: prices per kg are not used, so
    a weighted product gets no price test in matching for now."""
    if not product_ids:
        return {}
    medians = repository.median_prices(session, sorted(set(product_ids)), "regular")
    return {product_id: round(median) for product_id, median in medians.items()}


@dataclass(frozen=True, slots=True)
class PricingReassign:
    observations: int
    promotion_products: int


def reassign_product(session: Session, remove: uuid.UUID, keep: uuid.UUID) -> PricingReassign:
    """Pricing's part of merging remove into keep (Story 4.5): remove's observations and
    promotions belong to keep. Only which product an observation belongs to changes: its price,
    time and source never do (AD-3), and none is deleted. A promotion of both keeps one row.
    current_prices is not refreshed here: the caller refreshes it once the merge is done. Does
    not commit."""
    return PricingReassign(
        observations=repository.reassign_observations(session, remove, keep),
        promotion_products=repository.reassign_promotion_products(session, remove, keep),
    )
