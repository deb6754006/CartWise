"""matching: match_candidates; catalog: proposed and merged_into products; pricing: an index of
current_prices by product, for the median price of a candidate (Story 4.2). Schema only, no data.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_products_status"), "products", type_="check")
    op.create_check_constraint(
        op.f("ck_products_status"),
        "products",
        "status IN ('active', 'proposed', 'merged_into')",
    )
    op.create_table(
        "match_candidates",
        sa.Column("alias_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Numeric(4, 3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rank >= 1 AND rank <= 3", name=op.f("ck_match_candidates_rank")),
        sa.CheckConstraint("score >= 0 AND score <= 1", name=op.f("ck_match_candidates_score")),
        sa.ForeignKeyConstraint(
            ["alias_id"],
            ["product_aliases.id"],
            name=op.f("fk_match_candidates_alias_id_product_aliases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_match_candidates_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("alias_id", "rank", name=op.f("pk_match_candidates")),
    )
    op.create_index("ix_match_candidates_product_id", "match_candidates", ["product_id"])
    # The view's unique index leads with store_id; the median of a product reads all its stores.
    op.execute("CREATE INDEX ix_current_prices_product_id ON current_prices (product_id)")


def downgrade() -> None:
    # The old CHECK allows only active products: say so, rather than fail on the constraint.
    others = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM products WHERE status <> 'active'"))
        .scalar_one()
    )
    if others:
        raise RuntimeError(
            f"cannot downgrade below 0012: {others} products are proposed or merged_into; "
            "approve, merge or delete them first"
        )
    op.execute("DROP INDEX ix_current_prices_product_id")
    op.drop_index("ix_match_candidates_product_id", table_name="match_candidates")
    op.drop_table("match_candidates")
    op.drop_constraint(op.f("ck_products_status"), "products", type_="check")
    op.create_check_constraint(op.f("ck_products_status"), "products", "status IN ('active')")
