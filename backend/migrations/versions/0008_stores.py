"""catalog: stores (Story 3.3). Schema only, no data.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.types import UserDefinedType

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _Geography(UserDefinedType[Any]):
    # A copy of catalog.models.Geography: a migration does not import the app's models.
    cache_ok = True

    def get_col_spec(self, **_kw: Any) -> str:
        return "geography(Point,4326)"


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("gov_store_code", sa.Text(), nullable=False),
        sa.Column("sub_chain_code", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_norm", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("city_code", sa.Text(), nullable=True),
        sa.Column("zip_code", sa.Text(), nullable=True),
        sa.Column("store_type", sa.SmallInteger(), nullable=True),
        sa.Column("location", _Geography(), nullable=True),
        sa.Column("location_source", sa.String(16), nullable=True),
        sa.Column("geocoded_query", sa.Text(), nullable=True),
        sa.Column("geocode_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'needs_location', 'online')", name=op.f("ck_stores_status")
        ),
        sa.CheckConstraint(
            "location_source IN ('geocoded', 'manual')", name=op.f("ck_stores_location_source")
        ),
        sa.ForeignKeyConstraint(
            ["chain_id"], ["chains.id"], name=op.f("fk_stores_chain_id_chains")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
        sa.UniqueConstraint(
            "chain_id", "gov_store_code", name=op.f("uq_stores_chain_id_gov_store_code")
        ),
    )
    op.create_index("ix_stores_location", "stores", ["location"], postgresql_using="gist")


def downgrade() -> None:
    op.drop_index("ix_stores_location", table_name="stores", postgresql_using="gist")
    op.drop_table("stores")
