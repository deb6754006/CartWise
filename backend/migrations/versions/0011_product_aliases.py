"""catalog: product_aliases (Story 4.1). Schema only, no data.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("alias_text", sa.Text(), nullable=False),
        sa.Column("alias_norm", sa.Text(), nullable=False),
        sa.Column("barcode", sa.Text(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('certain', 'uncertain', 'final', 'disputed')",
            name=op.f("ck_product_aliases_state"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name=op.f("ck_product_aliases_confidence")
        ),
        sa.ForeignKeyConstraint(
            ["chain_id"], ["chains.id"], name=op.f("fk_product_aliases_chain_id_chains")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_product_aliases_product_id_products")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_aliases")),
        # NULL is one barcode value here: an alias with no barcode is unique per chain and text.
        sa.UniqueConstraint(
            "chain_id",
            "alias_norm",
            "barcode",
            name="uq_product_aliases_chain_id_alias_norm_barcode",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_product_aliases_product_id", "product_aliases", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_product_aliases_product_id", table_name="product_aliases")
    op.drop_table("product_aliases")
