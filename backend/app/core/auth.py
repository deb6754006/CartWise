"""Request identity (AD-12). The only place the server works out who is calling.

Endpoints depend on `get_subject` (anonymous allowed) or `require_subject` (anonymous
rejected) and never decode tokens themselves. The token kind is chosen by the JWT header:
RS256 is a Firebase ID token (registered user), anything else goes down the device-token
path (which accepts HS256 with typ=device only).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

import jwt
from fastapi import Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_session_factory
from app.core.errors import AppError
from app.core.firebase import ALGORITHM as FIREBASE_ALGORITHM
from app.core.firebase import FirebaseVerifier, auth_unavailable, get_firebase_verifier
from app.core.tokens import decode_device_token, invalid_token
from app.modules.identity import service as identity_service

type SubjectKind = Literal["user", "device", "anonymous"]

AUTH_REQUIRED_HE = "נדרשת התחברות"
DB_UNAVAILABLE_HE = "בסיס הנתונים לא זמין"
NOT_LINKED_HE = "החשבון עדיין לא חובר, נסו להתחבר שוב"
FORBIDDEN_HE = "אין הרשאה"


@dataclass(frozen=True, slots=True)
class Subject:
    kind: SubjectKind
    id: str | None


ANONYMOUS = Subject(kind="anonymous", id=None)


def auth_required() -> AppError:
    return AppError("auth_required", AUTH_REQUIRED_HE, status=401)


def not_linked() -> AppError:
    return AppError("not_linked", NOT_LINKED_HE, status=401)


def forbidden() -> AppError:
    return AppError("forbidden", FORBIDDEN_HE, status=403)


def db_unavailable() -> AppError:
    return AppError("db_unavailable", DB_UNAVAILABLE_HE, status=503)


def bearer_token(request: Request) -> str | None:
    """The bearer token, None without an Authorization header; 401 when malformed."""
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise invalid_token()
    return token


def is_firebase_token(token: str) -> bool:
    try:
        return jwt.get_unverified_header(token).get("alg") == FIREBASE_ALGORITHM
    except jwt.PyJWTError:
        raise invalid_token() from None


def get_subject(
    request: Request,
    session_factory: Annotated[Callable[[], Session], Depends(get_session_factory)],
    verifier: Annotated[FirebaseVerifier, Depends(get_firebase_verifier)],
) -> Subject:
    # The header is checked first; a session is opened only for a well-formed token.
    token = bearer_token(request)
    if token is None:
        return ANONYMOUS
    if is_firebase_token(token):
        return _user_subject(verifier.verify(token), session_factory)

    device_id = decode_device_token(token)
    try:
        with session_factory() as session:
            exists = identity_service.device_exists(session, device_id)
    except SQLAlchemyError:
        raise db_unavailable() from None
    if not exists:
        raise invalid_token()
    return Subject(kind="device", id=str(device_id))


def _user_subject(firebase_uid: str, session_factory: Callable[[], Session]) -> Subject:
    try:
        with session_factory() as session:
            user = identity_service.user_for_firebase_uid(session, firebase_uid)
    except SQLAlchemyError:
        raise db_unavailable() from None
    if user is None:
        raise not_linked()
    if user.deleted:
        raise invalid_token()
    return Subject(kind="user", id=str(user.id))


def require_subject(subject: Annotated[Subject, Depends(get_subject)]) -> Subject:
    if subject.kind == "anonymous":
        raise auth_required()
    return subject


def require_firebase_uid(
    request: Request,
    verifier: Annotated[FirebaseVerifier, Depends(get_firebase_verifier)],
) -> str:
    """For /v1/auth/link: a verified Firebase ID token whose user may not exist yet."""
    token = bearer_token(request)
    if token is None:
        raise auth_required()
    # Configuration is checked before the token kind, so an unconfigured server always
    # answers 503 on link, whatever was sent.
    if not verifier.configured:
        raise auth_unavailable()
    if not is_firebase_token(token):
        raise invalid_token()
    return verifier.verify(token)


def require_operator(
    request: Request,
    session_factory: Annotated[Callable[[], Session], Depends(get_session_factory)],
    verifier: Annotated[FirebaseVerifier, Depends(get_firebase_verifier)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> uuid.UUID:
    """For the match admin tool (Story 4.5): the user_id of an operator, a registered user whose
    Firebase UID is in OPERATOR_FIREBASE_UIDS. No token: 401 auth_required. Sign-in not
    configured: 503 auth_unavailable. A valid device token, a UID not in the list, or a user
    that does not exist or was deleted: 403 forbidden. An invalid or malformed token: 401
    invalid_token."""
    token = bearer_token(request)
    if token is None:
        raise auth_required()
    # As on link: an unconfigured server answers 503, whatever was sent.
    if not verifier.configured:
        raise auth_unavailable()
    if not is_firebase_token(token):
        # A valid device token is a guest: forbidden. Anything else is 401 invalid_token.
        decode_device_token(token)
        raise forbidden()
    firebase_uid = verifier.verify(token)
    if firebase_uid not in settings.operator_firebase_uids:
        raise forbidden()
    try:
        with session_factory() as session:
            user = identity_service.user_for_firebase_uid(session, firebase_uid)
    except SQLAlchemyError:
        raise db_unavailable() from None
    if user is None or user.deleted:
        raise forbidden()
    return user.id
