"""Error type and handlers. Every error response uses the AD-13 format:

{"error": {"code": str, "message_he": str, "details": object}}

Unhandled exceptions (500) are handled in core.logging.RequestIdMiddleware.
"""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

INTERNAL_ERROR_HE = "אירעה שגיאה בשרת"
VALIDATION_ERROR_HE = "הנתונים שנשלחו לא תקינים"

_HTTP_CODES: dict[int, tuple[str, str]] = {
    400: ("bad_request", "בקשה לא תקינה"),
    401: ("unauthorized", "נדרשת התחברות"),
    403: ("forbidden", "אין הרשאה"),
    404: ("not_found", "המשאב לא נמצא"),
    405: ("method_not_allowed", "הפעולה לא נתמכת"),
    409: ("conflict", "התנגשות"),
    429: ("rate_limited", "יותר מדי בקשות"),
}


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message_he: str,
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.message_he = message_he
        self.status = status
        self.details: dict[str, Any] = details or {}


def error_body(code: str, message_he: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message_he": message_he,
            "details": details if details is not None else {},
        }
    }


def error_response(
    status: int,
    code: str,
    message_he: str,
    details: Any = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=jsonable_encoder(error_body(code, message_he, details)),
        headers=headers,
    )


async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101
    return error_response(exc.status, exc.code, exc.message_he, exc.details)


def _http_code(status: int) -> tuple[str, str]:
    if status in _HTTP_CODES:
        return _HTTP_CODES[status]
    if status == 500:
        return "internal_error", INTERNAL_ERROR_HE
    if status == 422:
        return "validation_error", VALIDATION_ERROR_HE
    if status > 500:
        try:
            return HTTPStatus(status).name.lower(), INTERNAL_ERROR_HE
        except ValueError:
            return "server_error", INTERNAL_ERROR_HE
    try:
        return HTTPStatus(status).name.lower(), "שגיאה בבקשה"
    except ValueError:
        return "http_error", "שגיאה בבקשה"


async def http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code, message_he = _http_code(exc.status_code)
    return error_response(exc.status_code, code, message_he, {}, headers=exc.headers)


async def validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return error_response(422, "validation_error", VALIDATION_ERROR_HE, {"errors": errors})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
