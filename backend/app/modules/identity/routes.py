"""identity: HTTP routes. Calls service only, never repository."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.auth import Subject, auth_required, require_firebase_uid, require_subject
from app.core.db import get_session
from app.modules.identity import service
from app.modules.identity.schemas import (
    BrandIdsIn,
    ClubIdsIn,
    ClubIdsOut,
    DeviceRegisterIn,
    DeviceRegisterOut,
    LinkIn,
    LinkOut,
    MeOut,
    MyBrandOut,
    MyBrandsOut,
    PrefsIn,
    PrefsOut,
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


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={403: {"description": "A guest (device token): account_required"}},
)
def delete_me(
    subject: Annotated[Subject, Depends(require_subject)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    """Delete this registered account now (FR-6). Its row is purged 30 days later."""
    if subject.kind != "user":
        raise service.account_required()
    service.delete_account(session, _subject_uuid(subject))


def _subject_uuid(subject: Subject) -> uuid.UUID:
    if subject.id is None:
        raise auth_required()
    return uuid.UUID(subject.id)


@router.get("/me/clubs")
def get_my_clubs(
    subject: Annotated[Subject, Depends(require_subject)],
    session: Annotated[Session, Depends(get_session)],
) -> ClubIdsOut:
    return ClubIdsOut(club_ids=service.club_ids_for_subject(session, _subject_uuid(subject)))


@router.put("/me/clubs")
def put_my_clubs(
    body: ClubIdsIn,
    subject: Annotated[Subject, Depends(require_subject)],
    session: Annotated[Session, Depends(get_session)],
) -> ClubIdsOut:
    """Replace the whole set of clubs marked by this subject."""
    return ClubIdsOut(club_ids=service.set_clubs(session, _subject_uuid(subject), body.club_ids))


@router.get("/me/brands")
def get_my_brands(
    subject: Annotated[Subject, Depends(require_subject)],
    session: Annotated[Session, Depends(get_session)],
) -> MyBrandsOut:
    brands = service.brands_for_subject(session, _subject_uuid(subject))
    return MyBrandsOut(brands=[MyBrandOut(id=b.id, name=b.name) for b in brands])


@router.put("/me/brands")
def put_my_brands(
    body: BrandIdsIn,
    subject: Annotated[Subject, Depends(require_subject)],
    session: Annotated[Session, Depends(get_session)],
) -> MyBrandsOut:
    """Replace the whole set of brands this subject wants."""
    brands = service.set_brands(session, _subject_uuid(subject), body.brand_ids)
    return MyBrandsOut(brands=[MyBrandOut(id=b.id, name=b.name) for b in brands])


@router.get("/me/prefs")
def get_my_prefs(
    subject: Annotated[Subject, Depends(require_subject)],
    session: Annotated[Session, Depends(get_session)],
) -> PrefsOut:
    prefs = service.prefs_for_subject(session, _subject_uuid(subject))
    return PrefsOut(default_mode=prefs.default_mode, default_minutes=prefs.default_minutes)


@router.put("/me/prefs")
def put_my_prefs(
    body: PrefsIn,
    subject: Annotated[Subject, Depends(require_subject)],
    session: Annotated[Session, Depends(get_session)],
) -> PrefsOut:
    """Save this subject's default range."""
    prefs = service.set_prefs(
        session, _subject_uuid(subject), body.default_mode, body.default_minutes
    )
    return PrefsOut(default_mode=prefs.default_mode, default_minutes=prefs.default_minutes)
