"""catalog: brands; identity: user_brands (Story 1.4). Schema only, no data.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_norm", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brands")),
        sa.UniqueConstraint("name", name=op.f("uq_brands_name")),
    )
    # pg_trgm is enabled by 0001.
    op.create_index(
        "ix_brands_name_norm",
        "brands",
        ["name_norm"],
        postgresql_using="gin",
        postgresql_ops={"name_norm": "gin_trgm_ops"},
    )
    op.create_table(
        "user_brands",
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_user_brands_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("subject_id", "brand_id", name=op.f("pk_user_brands")),
    )
    op.create_index(op.f("ix_user_brands_brand_id"), "user_brands", ["brand_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_user_brands_brand_id"), table_name="user_brands")
    op.drop_table("user_brands")
    op.drop_index("ix_brands_name_norm", table_name="brands")
    op.drop_table("brands")
