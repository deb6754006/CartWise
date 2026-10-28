"""identity: SQLAlchemy models (tables owned by this module)."""

import uuid
from datetime import datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id


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
