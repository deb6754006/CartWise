"""identity: data access. Only this module's repository touches its tables."""

import uuid

from sqlalchemy import Boolean, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.modules.identity.models import Device


def upsert_device(session: Session, install_id_hash: str) -> tuple[uuid.UUID, bool]:
    """Insert a device, or touch last_seen_at if the hash exists. Returns (id, created)."""
    stmt = (
        insert(Device)
        .values(id=new_id(), install_id_hash=install_id_hash)
        .on_conflict_do_update(
            index_elements=[Device.install_id_hash],
            set_={"last_seen_at": func.now()},
        )
        # Postgres-specific: in RETURNING, xmax is 0 for a row this statement inserted and
        # non-zero for one it updated via ON CONFLICT. One round trip, no race between a
        # SELECT and an INSERT. Covered by the 201/200 integration tests.
        .returning(Device.id, literal_column("(xmax = 0)", Boolean))
    )
    row = session.execute(stmt).one()
    return row[0], bool(row[1])


def device_exists(session: Session, device_id: uuid.UUID) -> bool:
    return session.execute(select(Device.id).where(Device.id == device_id)).first() is not None
