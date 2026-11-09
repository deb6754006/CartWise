"""matching: match_votes (Story 4.3). Schema only, no data.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_votes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alias_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("vote", sa.String(16), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "vote IN ('confirm', 'other', 'unknown')", name=op.f("ck_match_votes_vote")
        ),
        sa.CheckConstraint("role IN ('user', 'operator')", name=op.f("ck_match_votes_role")),
        sa.CheckConstraint(
            "(vote = 'other') = (product_id IS NOT NULL)", name=op.f("ck_match_votes_product_id")
        ),
        sa.ForeignKeyConstraint(
            ["alias_id"],
            ["product_aliases.id"],
            name=op.f("fk_match_votes_alias_id_product_aliases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_match_votes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_match_votes_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_match_votes")),
        sa.UniqueConstraint("alias_id", "user_id", name="uq_match_votes_alias_id_user_id"),
    )
    op.create_index("ix_match_votes_user_id", "match_votes", ["user_id"])
    op.create_index("ix_match_votes_product_id", "match_votes", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_match_votes_product_id", table_name="match_votes")
    op.drop_index("ix_match_votes_user_id", table_name="match_votes")
    op.drop_table("match_votes")
