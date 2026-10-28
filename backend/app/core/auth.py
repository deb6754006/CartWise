"""Request identity (AD-12). The only place the server works out who is calling.

Endpoints depend on `get_subject` (anonymous allowed) or `require_subject` (anonymous
rejected) and never decode tokens themselves.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_session_factory
from app.core.errors import AppError
from app.core.tokens import decode_device_token, invalid_token
from app.modules.identity import service as identity_service

type SubjectKind = Literal["user", "device", "anonymous"]

AUTH_REQUIRED_HE = "נדרשת התחברות"
DB_UNAVAILABLE_HE = "בסיס הנתונים לא זמין"


@dataclass(frozen=True, slots=True)
class Subject:
    kind: SubjectKind
    id: str | None


ANONYMOUS = Subject(kind="anonymous", id=None)


def auth_required() -> AppError:
    return AppError("auth_required", AUTH_REQUIRED_HE, status=401)


def get_subject(
    request: Request,
    session_factory: Annotated[Callable[[], Session], Depends(get_session_factory)],
) -> Subject:
    # The header is checked first; a session is opened only for a well-formed token.
    header = request.headers.get("authorization")
    if header is None:
        return ANONYMOUS
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise invalid_token()
    device_id = decode_device_token(token)

    try:
        with session_factory() as session:
            exists = identity_service.device_exists(session, device_id)
    except SQLAlchemyError:
        raise AppError("db_unavailable", DB_UNAVAILABLE_HE, status=503) from None
    if not exists:
        raise invalid_token()
    return Subject(kind="device", id=str(device_id))


def require_subject(subject: Annotated[Subject, Depends(get_subject)]) -> Subject:
    if subject.kind == "anonymous":
        raise auth_required()
    return subject
