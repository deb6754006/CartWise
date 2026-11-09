"""matching: SQLAlchemy models (tables owned by this module)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, SmallInteger, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# How many candidates of an uncertain alias are kept.
MAX_KEPT_CANDIDATES = 3


class MatchCandidate(Base):
    """One of the top candidates of an uncertain alias, by rank (1 is the best). Replaced each
    time the alias is matched again, and removed when it is matched with certainty or a new
    product is proposed for it."""

    __tablename__ = "match_candidates"
    __table_args__ = (
        CheckConstraint(f"rank >= 1 AND rank <= {MAX_KEPT_CANDIDATES}", name="rank"),
        CheckConstraint("score >= 0 AND score <= 1", name="score"),
        Index("ix_match_candidates_product_id", "product_id"),
    )

    alias_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_aliases.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE")
    )
    score: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
