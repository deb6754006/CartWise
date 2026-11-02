"""identity: data access. Only this module's repository touches its tables."""

import uuid
from collections.abc import Collection

from sqlalchemy import Boolean, Uuid, delete, func, literal, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.modules.identity.models import Device, User, UserClub


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


def get_user_by_firebase_uid(session: Session, firebase_uid: str) -> User | None:
    stmt = select(User).where(User.firebase_uid == firebase_uid)
    return session.execute(stmt).scalar_one_or_none()


def get_or_create_user(session: Session, firebase_uid: str) -> tuple[User, bool]:
    """Find the user by firebase_uid, or insert it. Returns (user, created). Race-safe."""
    inserted = session.execute(
        insert(User)
        .values(id=new_id(), firebase_uid=firebase_uid)
        .on_conflict_do_nothing(index_elements=[User.firebase_uid])
        .returning(User.id)
    ).first()
    user = session.execute(select(User).where(User.firebase_uid == firebase_uid)).scalar_one()
    return user, inserted is not None


def lock_device(session: Session, device_id: uuid.UUID) -> Device | None:
    """The device row, locked (FOR UPDATE) until the transaction ends."""
    return session.execute(
        select(Device).where(Device.id == device_id).with_for_update()
    ).scalar_one_or_none()


def set_device_user(session: Session, device: Device, user_id: uuid.UUID) -> None:
    device.user_id = user_id
    session.flush()


def club_ids_for_subject(session: Session, subject_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = (
        select(UserClub.club_id).where(UserClub.subject_id == subject_id).order_by(UserClub.club_id)
    )
    return list(session.execute(stmt).scalars())


def _lock_subject_clubs(session: Session, subject_id: uuid.UUID) -> None:
    """Serialize writers of one subject's clubs until the transaction ends. Without this, two
    concurrent replacements (or a replacement and a transfer) could leave a mix of both."""
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(subject_id), 0))))


def replace_user_clubs(
    session: Session, subject_id: uuid.UUID, club_ids: Collection[uuid.UUID]
) -> None:
    _lock_subject_clubs(session, subject_id)
    session.execute(delete(UserClub).where(UserClub.subject_id == subject_id))
    if club_ids:
        session.execute(
            insert(UserClub),
            [{"subject_id": subject_id, "club_id": club_id} for club_id in club_ids],
        )


def move_user_clubs(session: Session, from_subject: uuid.UUID, to_subject: uuid.UUID) -> None:
    """Union from_subject's clubs into to_subject's, and empty from_subject's. Idempotent."""
    _lock_subject_clubs(session, from_subject)
    _lock_subject_clubs(session, to_subject)
    session.execute(
        insert(UserClub)
        .from_select(
            ["subject_id", "club_id"],
            select(literal(to_subject, Uuid), UserClub.club_id).where(
                UserClub.subject_id == from_subject
            ),
        )
        .on_conflict_do_nothing()
    )
    session.execute(delete(UserClub).where(UserClub.subject_id == from_subject))
