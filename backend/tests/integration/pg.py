"""Shared helpers for the integration tests (Postgres via testcontainers)."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import text

from app.core.db import make_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]
POSTGIS_IMAGE = "postgis/postgis:16-3.4"


def alembic_config(url: str | None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    if url is not None:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


def create_database(db_url: str, name: str) -> str:
    """Create an empty database (from template0) next to db_url and return its URL."""
    admin = make_engine(db_url).execution_options(isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
    finally:
        admin.dispose()
    return db_url.rsplit("/", 1)[0] + f"/{name}"
