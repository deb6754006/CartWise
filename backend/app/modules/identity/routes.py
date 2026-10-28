"""identity: HTTP routes. Calls service only, never repository."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.auth import Subject, auth_required, require_subject
from app.core.db import get_session
from app.modules.identity import service
from app.modules.identity.schemas import DeviceRegisterIn, DeviceRegisterOut, MeOut

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


@router.get("/me")
def me(subject: Annotated[Subject, Depends(require_subject)]) -> MeOut:
    if subject.kind == "anonymous" or subject.id is None:
        raise auth_required()
    return MeOut(kind=subject.kind, id=uuid.UUID(subject.id))
