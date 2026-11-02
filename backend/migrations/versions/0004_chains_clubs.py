"""catalog: chains, clubs; identity: user_clubs (Story 1.3). Schema only, no data.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chains",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("gov_chain_code", sa.String(32), nullable=True),
        sa.Column("publishes_files", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chains")),
        sa.UniqueConstraint("gov_chain_code", name=op.f("uq_chains_gov_chain_code")),
    )
    op.create_table(
        "clubs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(["chain_id"], ["chains.id"], name=op.f("fk_clubs_chain_id_chains")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clubs")),
        sa.UniqueConstraint("chain_id", "name", name=op.f("uq_clubs_chain_id")),
    )
    op.create_table(
        "user_clubs",
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("club_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["club_id"],
            ["clubs.id"],
            name=op.f("fk_user_clubs_club_id_clubs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("subject_id", "club_id", name=op.f("pk_user_clubs")),
    )
    op.create_index(op.f("ix_user_clubs_club_id"), "user_clubs", ["club_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_user_clubs_club_id"), table_name="user_clubs")
    op.drop_table("user_clubs")
    op.drop_table("clubs")
    op.drop_table("chains")
