"""pricing: SQLAlchemy models (tables owned by this module).

pricing also owns the materialized view current_prices (created in migration 0009): the latest
valid observation of each (store_id, product_id, price_type). It is read with SQL, not mapped.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id

ObservationSource = Literal["official_file", "receipt"]
PriceType = Literal["regular", "promo", "club"]
PricePer = Literal["unit", "kg"]
ObservationStatus = Literal["valid", "conflicting", "pending_branch", "rejected"]
PromotionKind = Literal["fixed_price", "multi_buy", "percent"]
PromotionSource = Literal["official_file"]

OBSERVATION_SOURCES: tuple[ObservationSource, ...] = ("official_file", "receipt")
PRICE_TYPES: tuple[PriceType, ...] = ("regular", "promo", "club")
PRICE_PERS: tuple[PricePer, ...] = ("unit", "kg")
OBSERVATION_STATUSES: tuple[ObservationStatus, ...] = (
    "valid",
    "conflicting",
    "pending_branch",
    "rejected",
)
PROMOTION_KINDS: tuple[PromotionKind, ...] = ("fixed_price", "multi_buy", "percent")
PROMOTION_SOURCES: tuple[PromotionSource, ...] = ("official_file",)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class PriceObservation(Base):
    """One price seen for a product in a store. Append-only (AD-3): the price is never updated;
    only status may change, through pricing.service. A new one is written only when the price
    differs from the last valid one of the same source."""

    __tablename__ = "price_observations"
    __table_args__ = (
        CheckConstraint(_in("source", OBSERVATION_SOURCES), name="source"),
        CheckConstraint(_in("price_type", PRICE_TYPES), name="price_type"),
        CheckConstraint(_in("per", PRICE_PERS), name="per"),
        CheckConstraint(_in("status", OBSERVATION_STATUSES), name="status"),
        CheckConstraint("unit_price_agorot > 0", name="unit_price_agorot"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id"))
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"))
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chains.id"))
    source: Mapped[ObservationSource] = mapped_column(String(16))
    price_type: Mapped[PriceType] = mapped_column(String(16))
    unit_price_agorot: Mapped[int] = mapped_column(Integer)
    per: Mapped[PricePer] = mapped_column(String(8))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The file (or receipt) it came from.
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The user who contributed it (a receipt, Epic 6). No foreign key: identity's tables are
    # identity's, and a deleted account's observations stay.
    contributor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[ObservationStatus] = mapped_column(String(16))
    has_personal_discount: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# The latest observation of a product in a store, first.
Index(
    "ix_price_observations_store_product_observed",
    PriceObservation.store_id,
    PriceObservation.product_id,
    PriceObservation.observed_at.desc(),
)


class Promotion(Base):
    """A store's promotion, from the chain's PromoFull file. Keyed by (store_id,
    gov_promotion_id). club_id NULL is for every customer; a promotion that may be for a club
    only has the chain's club. In effect while starts_at <= now < ends_at."""

    __tablename__ = "promotions"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "gov_promotion_id", name="uq_promotions_store_id_gov_promotion_id"
        ),
        CheckConstraint(_in("kind", PROMOTION_KINDS), name="kind"),
        CheckConstraint(_in("source", PROMOTION_SOURCES), name="source"),
        CheckConstraint("min_qty > 0", name="min_qty"),
        CheckConstraint("bundle_price_agorot > 0", name="bundle_price_agorot"),
        CheckConstraint("percent > 0 AND percent <= 100", name="percent"),
        CheckConstraint("starts_at <= ends_at", name="dates"),
        Index("ix_promotions_store_id_ends_at", "store_id", "ends_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chains.id"))
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"))
    gov_promotion_id: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    club_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("clubs.id"), nullable=True)
    kind: Mapped[PromotionKind] = mapped_column(String(16))
    min_qty: Mapped[Decimal] = mapped_column(Numeric)
    bundle_price_agorot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percent: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[PromotionSource] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PromotionProduct(Base):
    """A product a promotion applies to."""

    __tablename__ = "promotion_products"
    # The promotions of a product (Epic 5 looks them up by product).
    __table_args__ = (Index("ix_promotion_products_product_id", "product_id"),)

    promotion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("promotions.id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id"), primary_key=True)
