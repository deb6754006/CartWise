"""ingestion: ingestion_files.series_key and ingestion_alerts (Story 3.5). Schema only.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Older rows keep NULL: they take no part in the record-drop comparison.
    op.add_column("ingestion_files", sa.Column("series_key", sa.String(64), nullable=True))
    op.create_index(
        "ix_ingestion_files_chain_id_series_key_created_at",
        "ingestion_files",
        ["chain_id", "series_key", "created_at"],
    )
    op.create_table(
        "ingestion_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('stale', 'record_drop', 'file_errors')",
            name=op.f("ck_ingestion_alerts_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["chain_id"], ["chains.id"], name=op.f("fk_ingestion_alerts_chain_id_chains")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_ingestion_alerts_run_id_ingestion_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_alerts")),
    )
    op.create_index(
        "uq_ingestion_alerts_chain_id_kind_open",
        "ingestion_alerts",
        ["chain_id", "kind"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ingestion_alerts_chain_id_kind_open", table_name="ingestion_alerts")
    op.drop_table("ingestion_alerts")
    op.drop_index("ix_ingestion_files_chain_id_series_key_created_at", table_name="ingestion_files")
    op.drop_column("ingestion_files", "series_key")
