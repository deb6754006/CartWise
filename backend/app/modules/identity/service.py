"""identity: business logic. Other modules use identity data only through this file."""

import hashlib
import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.tokens import decode_device_token, invalid_token, issue_device_token
from app.modules.catalog import service as catalog_service
from app.modules.identity import repository
from app.modules.identity.models import TravelMinutes, TravelMode

DEVICE_ALREADY_LINKED_HE = "המכשיר הזה כבר מחובר לחשבון אחר"
UNKNOWN_CLUB_HE = "אחד המועדונים שנבחרו לא קיים"
UNKNOWN_BRAND_HE = "אחד המותגים שנבחרו לא קיים"

# A transfer hook moves a guest's data (lists, prefs, quota...) from a device to a user.
# Owning modules register one through register_transfer_hook (AD-2): identity never touches
# their tables. Hooks run inside the link transaction, once per device, on its first link.
type TransferHook = Callable[[Session, uuid.UUID, uuid.UUID], None]
_TRANSFER_HOOKS: list[TransferHook] = []


@dataclass(frozen=True, slots=True)
class Prefs:
    default_mode: TravelMode
    default_minutes: TravelMinutes


# What a subject that saved no range gets, including whoever skips Onboarding.
DEFAULT_PREFS = Prefs(default_mode="car", default_minutes=15)


@dataclass(frozen=True, slots=True)
class DeviceRegistration:
    device_id: uuid.UUID
    device_token: str
    expires_at: datetime
    created: bool


def hash_install_id(install_id: str) -> str:
    return hashlib.sha256(install_id.encode("utf-8")).hexdigest()


def register_device(session: Session, install_id: str) -> DeviceRegistration:
    """Register a guest device (or re-register it) and issue a fresh device token."""
    device_id, created = repository.upsert_device(session, hash_install_id(install_id))
    session.commit()
    token, expires_at = issue_device_token(device_id)
    return DeviceRegistration(device_id, token, expires_at, created)


def device_exists(session: Session, device_id: uuid.UUID) -> bool:
    return repository.device_exists(session, device_id)


def register_transfer_hook(fn: TransferHook) -> TransferHook:
    """Register fn(session, from_device_id, to_user_id). Usable as a decorator; idempotent."""
    if fn not in _TRANSFER_HOOKS:
        _TRANSFER_HOOKS.append(fn)
    return fn


def unregister_transfer_hook(fn: TransferHook) -> None:
    if fn in _TRANSFER_HOOKS:
        _TRANSFER_HOOKS.remove(fn)


@dataclass(frozen=True, slots=True)
class UserRef:
    id: uuid.UUID
    deleted: bool


def user_for_firebase_uid(session: Session, firebase_uid: str) -> UserRef | None:
    user = repository.get_user_by_firebase_uid(session, firebase_uid)
    if user is None:
        return None
    return UserRef(id=user.id, deleted=user.deleted_at is not None)


def device_already_linked() -> AppError:
    return AppError("device_already_linked", DEVICE_ALREADY_LINKED_HE, status=409)


def link(session: Session, firebase_uid: str, device_token: str | None) -> tuple[uuid.UUID, bool]:
    """Find or create the user, and link the device to it. Returns (user_id, created).

    - Device already linked to this user: hooks do not run again.
    - Device linked to another user: 409 device_already_linked.
    - Device not linked yet: linked, then every transfer hook runs, in the same transaction.
    Whenever the device belongs to this user, clubs and brands marked on it move to the user, and
    so does its range, unless the user already has one (the device's row goes either way).
    That is a direct call, not a hook: these tables are identity's own, and a repeat link (after
    signing out and marking more as a guest) has to move them too.
    An invalid device token, or a deleted user, is 401 invalid_token. Nothing is committed
    on any error.
    """
    device_id = decode_device_token(device_token) if device_token is not None else None
    try:
        user, created = repository.get_or_create_user(session, firebase_uid)
        if user.deleted_at is not None:
            raise invalid_token()
        if device_id is not None:
            device = repository.lock_device(session, device_id)
            if device is None:
                raise invalid_token()
            if device.user_id is not None and device.user_id != user.id:
                raise device_already_linked()
            first_link = device.user_id is None
            if first_link:
                repository.set_device_user(session, device, user.id)
            repository.move_user_clubs(session, device_id, user.id)
            repository.move_user_brands(session, device_id, user.id)
            repository.move_user_prefs(session, device_id, user.id)
            if first_link:
                for hook in list(_TRANSFER_HOOKS):
                    hook(session, device_id, user.id)
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return user.id, created


def club_ids_for_subject(session: Session, subject_id: uuid.UUID) -> list[uuid.UUID]:
    """The clubs this subject (user or device) marked. Epic 5 reads club membership here."""
    return repository.club_ids_for_subject(session, subject_id)


def set_clubs(
    session: Session, subject_id: uuid.UUID, club_ids: Collection[uuid.UUID]
) -> list[uuid.UUID]:
    """Replace the subject's clubs. An unknown id (422 unknown_club) changes nothing."""
    wanted = set(club_ids)
    try:
        unknown = wanted - catalog_service.existing_club_ids(session, wanted)
        if unknown:
            raise AppError(
                "unknown_club",
                UNKNOWN_CLUB_HE,
                status=422,
                details={"club_ids": sorted(str(club_id) for club_id in unknown)},
            )
        repository.replace_user_clubs(session, subject_id, wanted)
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return sorted(wanted)


def brand_ids_for_subject(session: Session, subject_id: uuid.UUID) -> list[uuid.UUID]:
    """The brands this subject (user or device) wants. Epics 2 and 5 read them here."""
    return repository.brand_ids_for_subject(session, subject_id)


def brands_for_subject(session: Session, subject_id: uuid.UUID) -> list[catalog_service.BrandRef]:
    """The brands this subject wants, with their names, sorted by name."""
    return catalog_service.brands_by_ids(session, brand_ids_for_subject(session, subject_id))


def set_brands(
    session: Session, subject_id: uuid.UUID, brand_ids: Collection[uuid.UUID]
) -> list[catalog_service.BrandRef]:
    """Replace the subject's brands. An unknown id (422 unknown_brand) changes nothing."""
    wanted = set(brand_ids)
    try:
        unknown = wanted - catalog_service.existing_brand_ids(session, wanted)
        if unknown:
            raise AppError(
                "unknown_brand",
                UNKNOWN_BRAND_HE,
                status=422,
                details={"brand_ids": sorted(str(brand_id) for brand_id in unknown)},
            )
        repository.replace_user_brands(session, subject_id, wanted)
        brands = catalog_service.brands_by_ids(session, wanted)
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return brands


def prefs_for_subject(session: Session, subject_id: uuid.UUID) -> Prefs:
    """The default range of this subject (user or device). Epic 5 reads it here.

    A subject that saved none gets DEFAULT_PREFS. Reading creates no row.
    """
    row = repository.prefs_for_subject(session, subject_id)
    if row is None:
        return DEFAULT_PREFS
    return Prefs(default_mode=row.default_mode, default_minutes=row.default_minutes)


def set_prefs(
    session: Session, subject_id: uuid.UUID, mode: TravelMode, minutes: TravelMinutes
) -> Prefs:
    """Save the subject's default range, replacing the one it had."""
    try:
        repository.upsert_user_prefs(session, subject_id, mode, minutes)
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return Prefs(default_mode=mode, default_minutes=minutes)
