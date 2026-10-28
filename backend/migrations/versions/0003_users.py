"""identity: users table, and the devices.user_id FK + index (Google sign-in, Story 1.2).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("firebase_uid", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("firebase_uid", name=op.f("uq_users_firebase_uid")),
    )
    op.create_foreign_key(
        op.f("fk_devices_user_id_users"),
        "devices",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_devices_user_id"), "devices", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_devices_user_id"), table_name="devices")
    op.drop_constraint(op.f("fk_devices_user_id_users"), "devices", type_="foreignkey")
    op.drop_table("users")
