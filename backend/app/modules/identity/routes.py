"""identity: HTTP routes. Calls service only, never repository."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.auth import Subject, auth_required, require_firebase_uid, require_subject
from app.core.db import get_session
from app.modules.identity import service
from app.modules.identity.schemas import (
    DeviceRegisterIn,
    DeviceRegisterOut,
    LinkIn,
    LinkOut,
    MeOut,
)

# No prefix: identity owns top-level resources (/v1/devices, /v1/me).
router = APIRouter(tags=["identity"])


@router.post(
    "/devices",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": DeviceRegisterOut, "description": "Device already registered"}},
)
def register_device(
    body: DeviceRegisterIn,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> DeviceRegisterOut:
    reg = service.register_device(session, body.install_id)
    if not reg.created:
        response.status_code = status.HTTP_200_OK
    return DeviceRegisterOut(
        device_id=reg.device_id, device_token=reg.device_token, expires_at=reg.expires_at
    )


@router.post(
    "/auth/link",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": LinkOut, "description": "User already existed"}},
)
def link(
    response: Response,
    firebase_uid: Annotated[str, Depends(require_firebase_uid)],
    session: Annotated[Session, Depends(get_session)],
    body: Annotated[LinkIn | None, Body()] = None,
) -> LinkOut:
    """Link this device to the Google account behind the Firebase ID token (Bearer)."""
    device_token = body.device_token if body is not None else None
    user_id, created = service.link(session, firebase_uid, device_token)
    if not created:
        response.status_code = status.HTTP_200_OK
    return LinkOut(user_id=user_id)


@router.get("/me")
def me(subject: Annotated[Subject, Depends(require_subject)]) -> MeOut:
    if subject.kind == "anonymous" or subject.id is None:
        raise auth_required()
    return MeOut(kind=subject.kind, id=uuid.UUID(subject.id))
