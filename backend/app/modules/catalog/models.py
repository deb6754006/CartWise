"""catalog: SQLAlchemy models (tables owned by this module)."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id


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
