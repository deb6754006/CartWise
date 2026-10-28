import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import make_engine
from app.main import create_app
from tests.integration.pg import alembic_config, create_database

pytestmark = pytest.mark.integration

EXTENSIONS = {"postgis", "pg_trgm", "unaccent"}


def _installed_extensions(url: str) -> set[str]:
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            return set(conn.execute(text("SELECT extname FROM pg_extension")).scalars())
    finally:
        engine.dispose()


def test_extensions_installed(db_url: str) -> None:
    assert _installed_extensions(db_url) >= EXTENSIONS


def test_health_ok(db_url: str) -> None:
    client = TestClient(create_app(engine=make_engine(db_url)))
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}


def test_migrations_use_settings_database_url(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # A fresh database (from template0, so no extensions) proves env.py falls back to Settings.
    fresh_url = create_database(db_url, "cw_settings")
    assert not (_installed_extensions(fresh_url) & EXTENSIONS)

    monkeypatch.setenv("DATABASE_URL", fresh_url)
    get_settings.cache_clear()
    try:
        cfg = alembic_config(None)
        assert not cfg.get_main_option("sqlalchemy.url")
        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()
    assert _installed_extensions(fresh_url) >= EXTENSIONS
