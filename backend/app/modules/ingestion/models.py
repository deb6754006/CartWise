"""ingestion: SQLAlchemy models (tables owned by this module)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id

RunStatus = Literal["running", "succeeded", "partial", "failed", "abandoned"]
FileStatus = Literal["succeeded", "failed"]
# The file kinds ingested in the MVP. Partial files (Price, Promo) are not.
FileKind = Literal["stores", "price_full", "promo_full"]

RUN_STATUSES: tuple[RunStatus, ...] = ("running", "succeeded", "partial", "failed", "abandoned")
FILE_STATUSES: tuple[FileStatus, ...] = ("succeeded", "failed")
FILE_KINDS: tuple[FileKind, ...] = ("stores", "price_full", "promo_full")
# What an operator alert is about (Story 3.5, FR-16).
AlertKind = Literal["stale", "record_drop", "file_errors"]
ALERT_KINDS: tuple[AlertKind, ...] = ("stale", "record_drop", "file_errors")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class IngestionRun(Base):
    """One ingestion run of one chain: when, how many files, how many records, what failed."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="status"),
        Index("ix_ingestion_runs_chain_id_started_at", "chain_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chains.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[RunStatus] = mapped_column(String(16))
    # files_seen: the files selected for the run (the latest of each kind and store).
    files_seen: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    files_ingested: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    files_skipped: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    files_failed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    records: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class IngestionFile(Base):
    """One file of a run. A file is identified by (chain_id, file_name, file_hash) (AD-14):
    at most one succeeded row each, and a file with one is skipped. A failed file is retried."""

    __tablename__ = "ingestion_files"
    __table_args__ = (
        CheckConstraint(_in("status", FILE_STATUSES), name="status"),
        CheckConstraint(_in("kind", FILE_KINDS), name="kind"),
        Index(
            "uq_ingestion_files_chain_id_file_name_file_hash",
            "chain_id",
            "file_name",
            "file_hash",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
        ),
        Index(
            "ix_ingestion_files_chain_id_series_key_created_at",
            "chain_id",
            "series_key",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ingestion_runs.id"), index=True)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chains.id"))
    file_name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[FileKind] = mapped_column(String(16))
    # "<kind>:<store_code or ->": the files that follow one another (the PriceFull of one store).
    # NULL in rows written before Story 3.5.
    series_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # sha256 of the downloaded bytes. NULL only when the download itself failed.
    file_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[FileStatus] = mapped_column(String(16))
    records: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IngestionAlert(Base):
    """An operator alert about one chain's ingestion. At most one open (unresolved) alert of each
    kind per chain; it is sent again every INGEST_ALERT_REPEAT_HOURS until it is resolved."""

    __tablename__ = "ingestion_alerts"
    __table_args__ = (
        CheckConstraint(_in("kind", ALERT_KINDS), name="kind"),
        Index(
            "uq_ingestion_alerts_chain_id_kind_open",
            "chain_id",
            "kind",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chains.id"))
    kind: Mapped[AlertKind] = mapped_column(String(16))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # NULL until a send went through.
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The numbers behind the alert (e.g. prev, cur, pct). No names, no prices.
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The run that raised (or last confirmed) it. NULL for stale, which no run raises.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ingestion_runs.id"), nullable=True
    )
