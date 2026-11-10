"""catalog: product_aliases.occurrences and products.merged_into_id (Story 4.5). Schema only.

Existing aliases start at 0 occurrences.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_aliases",
        sa.Column("occurrences", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_product_aliases_occurrences"), "product_aliases", "occurrences >= 0"
    )
    op.create_index(
        "ix_product_aliases_state_occurrences",
        "product_aliases",
        ["state", sa.text("occurrences DESC"), "updated_at"],
    )
    op.add_column("products", sa.Column("merged_into_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_products_merged_into_id_products"),
        "products",
        "products",
        ["merged_into_id"],
        ["id"],
    )
    op.create_index("ix_products_merged_into_id", "products", ["merged_into_id"])


def downgrade() -> None:
    op.drop_index("ix_products_merged_into_id", table_name="products")
    op.drop_constraint(op.f("fk_products_merged_into_id_products"), "products", type_="foreignkey")
    op.drop_column("products", "merged_into_id")
    op.drop_index("ix_product_aliases_state_occurrences", table_name="product_aliases")
    op.drop_constraint(op.f("ck_product_aliases_occurrences"), "product_aliases", type_="check")
    op.drop_column("product_aliases", "occurrences")
