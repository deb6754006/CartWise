import contextlib
import os
from collections.abc import Iterator

import pytest
from alembic import command

from tests.integration.pg import POSTGIS_IMAGE, alembic_config


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    """One Postgres container for the whole run, migrated to head."""
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
        command.upgrade(alembic_config(url), "head")
        yield url
    finally:
        container.stop()
