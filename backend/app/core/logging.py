"""Structured JSON logging and the X-Request-ID middleware.

Never logs request bodies or Authorization headers.
"""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import INTERNAL_ERROR_HE, error_response

REQUEST_ID_HEADER = "X-Request-ID"
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime", "color_message"}
_MAX_REQUEST_ID_LEN = 128

access_logger = logging.getLogger("app.access")
error_logger = logging.getLogger("app.errors")

_base_record_factory = logging.getLogRecordFactory()


def _record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    # Capture request_id when the record is created; formatting may happen later.
    record = _base_record_factory(*args, **kwargs)
    record.request_id = request_id_var.get()
    return record


if getattr(_base_record_factory, "__name__", "") != "_record_factory":
    logging.setLogRecordFactory(_record_factory)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_") and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
    # The middleware below writes the access log; avoid duplicate lines.
    logging.getLogger("uvicorn.access").disabled = True


def _clean_request_id(raw: str | None) -> str:
    if raw and len(raw) <= _MAX_REQUEST_ID_LEN and raw.isascii() and raw.isprintable():
        return raw
    return uuid.uuid4().hex


class RequestIdMiddleware:
    """Pure ASGI middleware: assigns a request id, echoes it, and writes an access log."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming: str | None = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = _clean_request_id(incoming)
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send_wrapper(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            # Handled here (not in Starlette's outer ServerErrorMiddleware) so the log line
            # still carries request_id and the 500 response still carries X-Request-ID.
            error_logger.error(
                "unhandled_exception",
                exc_info=exc,
                extra={"method": scope.get("method"), "path": scope.get("path")},
            )
            if started:
                status = 500
                raise
            response = error_response(500, "internal_error", INTERNAL_ERROR_HE, {})
            await response(scope, receive, tracking_send)
        finally:
            access_logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            request_id_var.reset(token)
