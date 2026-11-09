"""matching: SQLAlchemy models (tables owned by this module)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id

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


VoteKind = Literal["confirm", "other", "unknown"]
VOTE_KINDS: tuple[VoteKind, ...] = ("confirm", "other", "unknown")
VoteRole = Literal["user", "operator"]
VOTE_ROLES: tuple[VoteRole, ...] = ("user", "operator")
VOTE_KEY_CONSTRAINT = "uq_match_votes_alias_id_user_id"


class MatchVote(Base):
    """A user's vote on an alias's match (Story 4.3): confirm (the alias's current product), other
    (product_id, another product) or unknown. One per user and alias: voting again replaces it.
    An operator's approval is a vote too, with role operator."""

    __tablename__ = "match_votes"
    __table_args__ = (
        UniqueConstraint("alias_id", "user_id", name=VOTE_KEY_CONSTRAINT),
        CheckConstraint("vote IN ('confirm', 'other', 'unknown')", name="vote"),
        CheckConstraint("role IN ('user', 'operator')", name="role"),
        CheckConstraint("(vote = 'other') = (product_id IS NOT NULL)", name="product_id"),
        Index("ix_match_votes_user_id", "user_id"),
        Index("ix_match_votes_product_id", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    alias_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_aliases.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=True
    )
    vote: Mapped[VoteKind] = mapped_column(String(16))
    role: Mapped[VoteRole] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
