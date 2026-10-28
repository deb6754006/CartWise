"""identity: business logic. Other modules use identity data only through this file."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.tokens import issue_device_token
from app.modules.identity import repository


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
