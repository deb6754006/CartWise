"""catalog: SQLAlchemy models (tables owned by this module)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.core.db import Base
from app.core.ids import new_id

StoreStatus = Literal["active", "needs_location", "online"]
LocationSource = Literal["geocoded", "manual"]

STORE_STATUSES: tuple[StoreStatus, ...] = ("active", "needs_location", "online")
LOCATION_SOURCES: tuple[LocationSource, ...] = ("geocoded", "manual")

PackUnit = Literal["unit", "g", "kg", "ml", "l"]
ProductStatus = Literal["active"]

PACK_UNITS: tuple[PackUnit, ...] = ("unit", "g", "kg", "ml", "l")
PRODUCT_STATUSES: tuple[ProductStatus, ...] = ("active",)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Geography(UserDefinedType[Any]):
    """PostGIS geography(Point,4326), with no new dependency. Values are written and read
    through SQL functions in the repository (ST_MakePoint, ST_Y, ST_X), never as Python values."""

    cache_ok = True

    def get_col_spec(self, **_kw: Any) -> str:
        return "geography(Point,4326)"


class Chain(Base):
    """A retail chain. An independent store is a chain with one branch."""

    __tablename__ = "chains"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    gov_chain_code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    publishes_files: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class Club(Base):
    """A chain's loyalty club. Members are never asked for a member number: no such column."""

    __tablename__ = "clubs"
    __table_args__ = (UniqueConstraint("chain_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chains.id"))
    name: Mapped[str] = mapped_column(String(200))


class Brand(Base):
    """A product brand. name_norm is set only from catalog.service.normalize_he(name)."""

    __tablename__ = "brands"
    __table_args__ = (
        # Trigram, because search matches a substring of name_norm.
        Index(
            "ix_brands_name_norm",
            "name_norm",
            postgresql_using="gin",
            postgresql_ops={"name_norm": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    name_norm: Mapped[str] = mapped_column(Text)


class Store(Base):
    """A chain's store, from the chain's Stores file. Keyed by (chain_id, gov_store_code).

    A physical store is active once it has a location, and needs_location until then. An online
    store (StoreType 2) is never located and never compared. Only stores that are active and have
    a location take part in comparisons.

    geocoded_query is the last text sent to the geocoder for this store, and geocode_attempted_at
    is when that attempt failed (NULL once one succeeded). A manual location is never replaced.
    """

    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("chain_id", "gov_store_code", name="uq_stores_chain_id_gov_store_code"),
        CheckConstraint(_in("status", STORE_STATUSES), name="status"),
        CheckConstraint(_in("location_source", LOCATION_SOURCES), name="location_source"),
        Index("ix_stores_location", "location", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chains.id"))
    # StoreID with no leading zeros ("001" -> "1", "000" -> "0").
    gov_store_code: Mapped[str] = mapped_column(Text)
    sub_chain_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(Text)
    # The CBS settlement code, as in the file (usually a number).
    city_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    zip_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    store_type: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    location: Mapped[Any] = mapped_column(Geography(), nullable=True)
    location_source: Mapped[LocationSource | None] = mapped_column(String(16), nullable=True)
    geocoded_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    geocode_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[StoreStatus] = mapped_column(String(16))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Product(Base):
    """A product. One with a barcode is keyed by it (unique); one without (such as produce sold by
    weight) is matched through matching.service (Story 3.6, Epic 4). name_norm is set only from
    catalog.service.normalize_he(name). The first name a barcode was seen with stays."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(_in("pack_unit", PACK_UNITS), name="pack_unit"),
        CheckConstraint(_in("status", PRODUCT_STATUSES), name="status"),
        CheckConstraint("pack_size > 0", name="pack_size"),
        # Trigram, because search matches a substring of name_norm.
        Index(
            "ix_products_name_norm",
            "name_norm",
            postgresql_using="gin",
            postgresql_ops={"name_norm": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    # As in the file, leading zeros kept.
    barcode: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("brands.id"), nullable=True)
    # No categories table yet: it comes with the category tree.
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    pack_size: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    pack_unit: Mapped[PackUnit | None] = mapped_column(String(8), nullable=True)
    is_weighted: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[ProductStatus] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


AliasState = Literal["certain", "uncertain", "final", "disputed"]

ALIAS_STATES: tuple[AliasState, ...] = ("certain", "uncertain", "final", "disputed")

# The key of an alias: a chain's name for a product, with its barcode (or with none).
ALIAS_KEY_CONSTRAINT = "uq_product_aliases_chain_id_alias_norm_barcode"


class ProductAlias(Base):
    """A chain's name for a product (in its files, or on a receipt line), with the product it was
    matched to. Rows are created only by matching, through catalog.service.

    alias_text is NFC with whitespace collapsed, and alias_norm is normalize_he(alias_text). A
    barcode is kept as it is; NULL (no barcode) is one key value, not a different one each time.
    """

    __tablename__ = "product_aliases"
    __table_args__ = (
        UniqueConstraint(
            "chain_id",
            "alias_norm",
            "barcode",
            name=ALIAS_KEY_CONSTRAINT,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(_in("state", ALIAS_STATES), name="state"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence"),
        Index("ix_product_aliases_product_id", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chains.id"))
    alias_text: Mapped[str] = mapped_column(Text)
    alias_norm: Mapped[str] = mapped_column(Text)
    barcode: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id"), nullable=True
    )
    state: Mapped[AliasState] = mapped_column(String(16))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
