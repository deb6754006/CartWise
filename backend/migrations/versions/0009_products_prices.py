"""catalog: products; pricing: price_observations, promotions, promotion_products and the
materialized view current_prices (Story 3.4). Schema only, no data.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The latest valid observation of each (store, product, price type). The newer id breaks a tie.
CURRENT_PRICES = """
CREATE MATERIALIZED VIEW current_prices AS
SELECT DISTINCT ON (store_id, product_id, price_type)
    store_id, product_id, price_type, unit_price_agorot, per, observed_at, id AS observation_id
FROM price_observations
WHERE status = 'valid'
ORDER BY store_id, product_id, price_type, observed_at DESC, id DESC
"""


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("barcode", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_norm", sa.Text(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("pack_size", sa.Numeric(), nullable=True),
        sa.Column("pack_unit", sa.String(8), nullable=True),
        sa.Column("is_weighted", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "pack_unit IN ('unit', 'g', 'kg', 'ml', 'l')", name=op.f("ck_products_pack_unit")
        ),
        sa.CheckConstraint("status IN ('active')", name=op.f("ck_products_status")),
        sa.CheckConstraint("pack_size > 0", name=op.f("ck_products_pack_size")),
        sa.ForeignKeyConstraint(
            ["brand_id"], ["brands.id"], name=op.f("fk_products_brand_id_brands")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("barcode", name=op.f("uq_products_barcode")),
    )
    op.create_index(
        "ix_products_name_norm",
        "products",
        ["name_norm"],
        postgresql_using="gin",
        postgresql_ops={"name_norm": "gin_trgm_ops"},
    )

    op.create_table(
        "price_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("price_type", sa.String(16), nullable=False),
        sa.Column("unit_price_agorot", sa.Integer(), nullable=False),
        sa.Column("per", sa.String(8), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("contributor_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("has_personal_discount", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('official_file', 'receipt')", name=op.f("ck_price_observations_source")
        ),
        sa.CheckConstraint(
            "price_type IN ('regular', 'promo', 'club')",
            name=op.f("ck_price_observations_price_type"),
        ),
        sa.CheckConstraint("per IN ('unit', 'kg')", name=op.f("ck_price_observations_per")),
        sa.CheckConstraint(
            "status IN ('valid', 'conflicting', 'pending_branch', 'rejected')",
            name=op.f("ck_price_observations_status"),
        ),
        sa.CheckConstraint(
            "unit_price_agorot > 0", name=op.f("ck_price_observations_unit_price_agorot")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_price_observations_product_id_products")
        ),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], name=op.f("fk_price_observations_store_id_stores")
        ),
        sa.ForeignKeyConstraint(
            ["chain_id"], ["chains.id"], name=op.f("fk_price_observations_chain_id_chains")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_observations")),
    )
    op.create_index(
        "ix_price_observations_store_product_observed",
        "price_observations",
        ["store_id", "product_id", sa.text("observed_at DESC")],
    )

    op.create_table(
        "promotions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("gov_promotion_id", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("club_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("min_qty", sa.Numeric(), nullable=False),
        sa.Column("bundle_price_agorot", sa.Integer(), nullable=True),
        sa.Column("percent", sa.Numeric(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('fixed_price', 'multi_buy', 'percent')", name=op.f("ck_promotions_kind")
        ),
        sa.CheckConstraint("source IN ('official_file')", name=op.f("ck_promotions_source")),
        sa.CheckConstraint("min_qty > 0", name=op.f("ck_promotions_min_qty")),
        sa.CheckConstraint(
            "bundle_price_agorot > 0", name=op.f("ck_promotions_bundle_price_agorot")
        ),
        sa.CheckConstraint("percent > 0 AND percent <= 100", name=op.f("ck_promotions_percent")),
        sa.CheckConstraint("starts_at <= ends_at", name=op.f("ck_promotions_dates")),
        sa.ForeignKeyConstraint(
            ["chain_id"], ["chains.id"], name=op.f("fk_promotions_chain_id_chains")
        ),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], name=op.f("fk_promotions_store_id_stores")
        ),
        sa.ForeignKeyConstraint(
            ["club_id"], ["clubs.id"], name=op.f("fk_promotions_club_id_clubs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promotions")),
        sa.UniqueConstraint(
            "store_id", "gov_promotion_id", name=op.f("uq_promotions_store_id_gov_promotion_id")
        ),
    )
    op.create_index("ix_promotions_store_id_ends_at", "promotions", ["store_id", "ends_at"])

    op.create_table(
        "promotion_products",
        sa.Column("promotion_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["promotion_id"],
            ["promotions.id"],
            name=op.f("fk_promotion_products_promotion_id_promotions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_promotion_products_product_id_products")
        ),
        sa.PrimaryKeyConstraint("promotion_id", "product_id", name=op.f("pk_promotion_products")),
    )

    op.create_index("ix_promotion_products_product_id", "promotion_products", ["product_id"])

    op.execute(CURRENT_PRICES)
    # Unique, so the view can be refreshed CONCURRENTLY.
    op.execute(
        "CREATE UNIQUE INDEX ux_current_prices ON current_prices (store_id, product_id, price_type)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW current_prices")
    op.drop_index("ix_promotion_products_product_id", table_name="promotion_products")
    op.drop_table("promotion_products")
    op.drop_index("ix_promotions_store_id_ends_at", table_name="promotions")
    op.drop_table("promotions")
    op.drop_index("ix_price_observations_store_product_observed", table_name="price_observations")
    op.drop_table("price_observations")
    op.drop_index("ix_products_name_norm", table_name="products", postgresql_using="gin")
    op.drop_table("products")
