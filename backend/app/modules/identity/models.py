"""identity: SQLAlchemy models (tables owned by this module)."""

import uuid
from datetime import datetime

from sqlalchemy import CHAR, DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id


class Device(Base):
    """A guest installation. Only a SHA-256 of the install id is stored (no PII).

    last_seen_at is the last registration time (POST /v1/devices), not the last request.
    """

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    install_id_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    # Linked user (Story 1.2). The FK to users is added together with that table.
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attestation_ok_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
