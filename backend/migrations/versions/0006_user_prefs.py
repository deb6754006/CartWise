"""identity: user_prefs, a subject's default range (Story 1.5). Schema only, no data.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_prefs",
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("default_mode", sa.String(8), nullable=False),
        sa.Column("default_minutes", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "default_mode IN ('walk', 'car')", name=op.f("ck_user_prefs_default_mode")
        ),
        sa.CheckConstraint(
            "default_minutes IN (5, 10, 15, 20, 30)", name=op.f("ck_user_prefs_default_minutes")
        ),
        sa.PrimaryKeyConstraint("subject_id", name=op.f("pk_user_prefs")),
    )


def downgrade() -> None:
    op.drop_table("user_prefs")
