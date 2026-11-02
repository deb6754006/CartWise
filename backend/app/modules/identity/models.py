"""identity: SQLAlchemy models (tables owned by this module)."""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id

# No public transport: it comes in version 1.1. The values match the checks on user_prefs.
TravelMode = Literal["walk", "car"]
TravelMinutes = Literal[5, 10, 15, 20, 30]


class User(Base):
    """A registered (Google) account. Only firebase_uid is stored: no name, email or phone."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Soft delete (Story 1.7). A deleted user's ID tokens are rejected.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Device(Base):
    """A guest installation. Only a SHA-256 of the install id is stored (no PII).

    last_seen_at is the last registration time (POST /v1/devices), not the last request.
    """

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    install_id_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    # Set by POST /v1/auth/link (Story 1.2); NULL while the device is a guest.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attestation_ok_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UserClub(Base):
    """A club a subject marked as a member of. Never a member number or any other identifier.

    subject_id is a user or a device, so it has no FK: UUIDv7 is unique across the two tables.
    """

    __tablename__ = "user_clubs"

    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    club_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clubs.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class UserBrand(Base):
    """A brand a subject wants. subject_id is a user or a device, so it has no FK (see UserClub)."""

    __tablename__ = "user_brands"

    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    brand_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class UserPrefs(Base):
    """A subject's default range: one row at most. subject_id has no FK (see UserClub).

    The user's location is never stored here.
    """

    __tablename__ = "user_prefs"
    __table_args__ = (
        CheckConstraint("default_mode IN ('walk', 'car')", name="default_mode"),
        CheckConstraint("default_minutes IN (5, 10, 15, 20, 30)", name="default_minutes"),
    )

    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    default_mode: Mapped[TravelMode] = mapped_column(String(8))
    default_minutes: Mapped[TravelMinutes] = mapped_column(SmallInteger)
