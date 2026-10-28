import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import make_engine
from app.main import create_app

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]
POSTGIS_IMAGE = "postgis/postgis:16-3.4"
EXTENSIONS = {"postgis", "pg_trgm", "unaccent"}


def _alembic_config(url: str | None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    if url is not None:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


def _installed_extensions(url: str) -> set[str]:
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            return set(conn.execute(text("SELECT extname FROM pg_extension")).scalars())
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    from testcontainers.community.postgres import PostgresContainer

    container = PostgresContainer(POSTGIS_IMAGE, driver="psycopg")
    try:
        container.start()
    except Exception as exc:
        with contextlib.suppress(Exception):  # best-effort cleanup of a half-started container
            container.stop()
        if os.environ.get("CARTWISE_REQUIRE_DOCKER") == "1":
            pytest.fail(f"Docker required (CARTWISE_REQUIRE_DOCKER=1) but unavailable: {exc}")
        pytest.skip(f"Docker not available: {exc}")
    try:
        url = container.get_connection_url()
        command.upgrade(_alembic_config(url), "head")
        yield url
    finally:
        container.stop()


def test_extensions_installed(db_url: str) -> None:
    assert _installed_extensions(db_url) >= EXTENSIONS


def test_health_ok(db_url: str) -> None:
    client = TestClient(create_app(engine=make_engine(db_url)))
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}


def test_migrations_use_settings_database_url(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # A fresh database (from template0, so no extensions) proves env.py falls back to Settings.
    admin = make_engine(db_url).execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("CREATE DATABASE cw_settings TEMPLATE template0"))
    admin.dispose()
    fresh_url = db_url.rsplit("/", 1)[0] + "/cw_settings"
    assert not (_installed_extensions(fresh_url) & EXTENSIONS)

    monkeypatch.setenv("DATABASE_URL", fresh_url)
    get_settings.cache_clear()
    try:
        cfg = _alembic_config(None)
        assert not cfg.get_main_option("sqlalchemy.url")
        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()
    assert _installed_extensions(fresh_url) >= EXTENSIONS
