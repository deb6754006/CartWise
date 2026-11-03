"""ingestion: ingestion_runs, ingestion_files (Story 3.2). Schema only, no data.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("files_seen", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("files_ingested", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("files_skipped", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("files_failed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("records", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed', 'abandoned')",
            name=op.f("ck_ingestion_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["chain_id"], ["chains.id"], name=op.f("fk_ingestion_runs_chain_id_chains")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
    )
    op.create_index(
        "ix_ingestion_runs_chain_id_started_at", "ingestion_runs", ["chain_id", "started_at"]
    )
    op.create_table(
        "ingestion_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("file_hash", sa.CHAR(64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("records", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')", name=op.f("ck_ingestion_files_status")
        ),
        sa.CheckConstraint(
            "kind IN ('stores', 'price_full', 'promo_full')", name=op.f("ck_ingestion_files_kind")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["ingestion_runs.id"], name=op.f("fk_ingestion_files_run_id_ingestion_runs")
        ),
        sa.ForeignKeyConstraint(
            ["chain_id"], ["chains.id"], name=op.f("fk_ingestion_files_chain_id_chains")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_files")),
    )
    op.create_index(op.f("ix_ingestion_files_run_id"), "ingestion_files", ["run_id"])
    op.create_index(
        "uq_ingestion_files_chain_id_file_name_file_hash",
        "ingestion_files",
        ["chain_id", "file_name", "file_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )


def downgrade() -> None:
    op.drop_index("uq_ingestion_files_chain_id_file_name_file_hash", table_name="ingestion_files")
    op.drop_index(op.f("ix_ingestion_files_run_id"), table_name="ingestion_files")
    op.drop_table("ingestion_files")
    op.drop_index("ix_ingestion_runs_chain_id_started_at", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
