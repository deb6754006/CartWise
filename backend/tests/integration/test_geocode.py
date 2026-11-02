"""GET /v1/geo/geocode against Postgres, with a fake geocoder: no network."""

import logging
from collections.abc import Iterator

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session, get_session_factory, make_engine
from app.core.firebase import get_firebase_verifier
from app.main import create_app
from app.modules.geo.service import (
    GeoPoint,
    NominatimGeocoder,
    geocoding_unavailable,
    get_geocoder,
)
from tests.integration.pg import alembic_config, create_database
from tests.integration.test_clubs import _device
from tests.integration.test_link import FakeVerifier

pytestmark = pytest.mark.integration

ADDRESS = "הרצל 1, תל אביב"
PATH = "/v1/geo/geocode"


def _server_log(caplog: pytest.LogCaptureFixture) -> str:
    """What the server logged. The "httpx" records are this test's own TestClient."""
    lines = [f"{r.getMessage()} {vars(r)}" for r in caplog.records if r.name != "httpx"]
    return " ".join(lines).upper()


class FakeGeocoder:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.result: GeoPoint | None = GeoPoint(lat=32.06, lng=34.77)
        self.fail = False

    def locate(self, address: str) -> GeoPoint | None:
        self.calls.append(address)
        if self.fail:
            raise geocoding_unavailable()
        return self.result


@pytest.fixture(scope="module")
def engine(db_url: str) -> Iterator[Engine]:
    url = create_database(db_url, "cw_geocode")
    command.upgrade(alembic_config(url), "head")
    eng = make_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
def geocoder() -> FakeGeocoder:
    return FakeGeocoder()


@pytest.fixture
def app(engine: Engine, geocoder: FakeGeocoder) -> FastAPI:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    application = create_app(engine=engine)

    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_session_factory] = lambda: factory
    application.dependency_overrides[get_firebase_verifier] = FakeVerifier
    application.dependency_overrides[get_geocoder] = lambda: geocoder
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    return _device(client)[1]


def test_the_path_is_the_one_the_app_calls(client: TestClient) -> None:
    assert PATH in client.get("/openapi.json").json()["paths"]


def test_found_returns_the_coordinates(
    client: TestClient, headers: dict[str, str], geocoder: FakeGeocoder
) -> None:
    resp = client.get(PATH, params={"q": ADDRESS}, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"lat": 32.06, "lng": 34.77}
    assert geocoder.calls == [ADDRESS]


def test_the_address_is_trimmed(
    client: TestClient, headers: dict[str, str], geocoder: FakeGeocoder
) -> None:
    assert client.get(PATH, params={"q": f"  {ADDRESS} "}, headers=headers).status_code == 200
    assert geocoder.calls == [ADDRESS]


def test_not_found_is_404(
    client: TestClient, headers: dict[str, str], geocoder: FakeGeocoder
) -> None:
    geocoder.result = None
    resp = client.get(PATH, params={"q": ADDRESS}, headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "address_not_found"
    assert ADDRESS not in resp.text


@pytest.mark.parametrize(
    "params",
    [{}, {"q": ""}, {"q": "א"}, {"q": "   "}, {"q": "  א  "}, {"q": "א" * 201}],
    ids=["missing", "empty", "one", "spaces", "one-padded", "too-long"],
)
def test_bad_input_is_422_with_no_lookup(
    client: TestClient,
    headers: dict[str, str],
    geocoder: FakeGeocoder,
    params: dict[str, str],
) -> None:
    resp = client.get(PATH, params=params, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
    assert geocoder.calls == []


def test_a_422_does_not_echo_the_address(client: TestClient, headers: dict[str, str]) -> None:
    resp = client.get(PATH, params={"q": "ש" * 201}, headers=headers)
    assert resp.status_code == 422
    assert "ש" * 201 not in resp.text


def test_the_limits_are_inclusive(
    client: TestClient, headers: dict[str, str], geocoder: FakeGeocoder
) -> None:
    for q in ("אב", "א" * 200, f" {'א' * 200} "):
        assert client.get(PATH, params={"q": q}, headers=headers).status_code == 200
    assert len(geocoder.calls) == 3


def test_a_failure_is_503_without_the_address(
    client: TestClient,
    headers: dict[str, str],
    geocoder: FakeGeocoder,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    geocoder.fail = True
    resp = client.get(PATH, params={"q": ADDRESS}, headers=headers)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "geocoding_unavailable"
    assert ADDRESS not in resp.text
    assert ADDRESS not in _server_log(caplog)


def test_without_a_token_is_401_with_no_lookup(client: TestClient, geocoder: FakeGeocoder) -> None:
    resp = client.get(PATH, params={"q": ADDRESS})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_required"
    assert geocoder.calls == []


def test_the_address_is_not_logged_on_success(
    client: TestClient, headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    assert client.get(PATH, params={"q": ADDRESS}, headers=headers).status_code == 200
    assert any(record.name == "app.access" for record in caplog.records)
    assert ADDRESS not in _server_log(caplog)
    assert "%D7" not in _server_log(caplog)  # nor percent-encoded


def test_the_real_geocoder_keeps_it_out_of_the_answer_and_the_logs(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The real parsing and error path, with only the network call replaced."""
    caplog.set_level(logging.DEBUG)

    def fetch(url: str) -> bytes:
        raise TimeoutError(url)

    app.dependency_overrides[get_geocoder] = lambda: NominatimGeocoder(
        "https://nominatim.test/search", fetch=fetch
    )
    resp = client.get(PATH, params={"q": ADDRESS}, headers=headers)
    assert resp.status_code == 503
    assert ADDRESS not in resp.text
    assert ADDRESS not in _server_log(caplog)
    assert "%D7" not in _server_log(caplog)


def test_nothing_is_stored(engine: Engine, client: TestClient, headers: dict[str, str]) -> None:
    assert client.get(PATH, params={"q": ADDRESS}, headers=headers).status_code == 200
    with engine.connect() as conn:
        for table in inspect(conn).get_table_names():
            if table in ("alembic_version", "spatial_ref_sys"):
                continue
            quoted = conn.dialect.identifier_preparer.quote(table)
            hits = conn.execute(
                text(f"SELECT count(*) FROM {quoted} t WHERE t::text LIKE :a"),  # noqa: S608
                {"a": f"%{ADDRESS}%"},
            ).scalar_one()
            assert hits == 0, table
