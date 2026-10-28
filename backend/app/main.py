"""FastAPI application factory."""

import logging

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core import db
from app.core.config import get_settings
from app.core.errors import error_response, register_error_handlers
from app.core.logging import RequestIdMiddleware, configure_logging
from app.modules.registry import ROUTERS

logger = logging.getLogger("app.health")


def create_app(engine: Engine | None = None) -> FastAPI:
    """Build the app. `engine` overrides the default DB engine (used by tests)."""
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    app = FastAPI(title="CartWise API", version="0.1.0")
    register_error_handlers(app)
    app.add_middleware(RequestIdMiddleware)

    health_engine = engine if engine is not None else db.engine
    v1 = APIRouter(prefix="/v1")

    @v1.get("/health", tags=["health"])
    def health() -> JSONResponse:
        try:
            with health_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            logger.warning("db_unavailable", extra={"error": type(exc).__name__})
            return error_response(503, "db_unavailable", "בסיס הנתונים לא זמין", {})
        return JSONResponse({"status": "ok", "db": "ok"})

    for router in ROUTERS:
        v1.include_router(router)
    app.include_router(v1)
    return app


app = create_app()
