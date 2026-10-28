import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DEV_DEVICE_TOKEN_SECRET
from app.core.db import get_session, get_session_factory, make_engine
from app.core.ids import new_id
from app.main import create_app
from tests.integration.pg import alembic_config, create_database

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine(db_url: str) -> Iterator[Engine]:
    eng = make_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine: Engine) -> TestClient:
    app = create_app(engine=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_session_factory] = lambda: factory
    return TestClient(app)


def _install_id() -> str:
    return str(uuid.uuid4())


def _rows(engine: Engine, install_id: str) -> list[dict[str, object]]:
    digest = hashlib.sha256(install_id.encode()).hexdigest()
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM devices WHERE install_id_hash = :h"), {"h": digest}
        )
        return [dict(r._mapping) for r in result]


def _register(client: TestClient, install_id: str) -> tuple[int, dict[str, str]]:
    resp = client.post("/v1/devices", json={"install_id": install_id})
    return resp.status_code, resp.json()


def _me(client: TestClient, token: str) -> tuple[int, dict[str, object]]:
    resp = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    return resp.status_code, resp.json()


def test_first_registration(client: TestClient, engine: Engine) -> None:
    install_id = _install_id()
    status, body = _register(client, install_id)
    assert status == 201
    assert set(body) == {"device_id", "device_token", "expires_at"}
    device_id = uuid.UUID(body["device_id"])
    assert device_id.version == 7

    expires_at = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert expires_at.utcoffset() == timedelta(0)
    assert timedelta(days=29) < expires_at - datetime.now(UTC) <= timedelta(days=30)

    rows = _rows(engine, install_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == device_id
    assert row["user_id"] is None
    assert row["attestation_ok_at"] is None
    # Only the hash is stored, never the install id itself.
    assert install_id not in {str(v) for v in row.values()}


def test_repeat_registration(client: TestClient, engine: Engine) -> None:
    install_id = _install_id()
    _, first = _register(client, install_id)
    seen_before = _rows(engine, install_id)[0]["last_seen_at"]

    status, second = _register(client, install_id)
    assert status == 200
    assert second["device_id"] == first["device_id"]
    assert second["device_token"]

    rows = _rows(engine, install_id)
    assert len(rows) == 1
    assert rows[0]["last_seen_at"] > seen_before  # type: ignore[operator]
    assert rows[0]["created_at"] < rows[0]["last_seen_at"]  # type: ignore[operator]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"install_id": ""},
        {"install_id": "x" * 15},
        {"install_id": "x" * 129},
        {"install_id": 7},
    ],
)
def test_invalid_install_id(client: TestClient, payload: dict[str, object]) -> None:
    resp = client.post("/v1/devices", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_install_id_lone_surrogate(client: TestClient) -> None:
    # Valid JSON, but not encodable as UTF-8 (so it cannot be hashed).
    raw = b'{"install_id": "\\ud800' + b"a" * 20 + b'"}'
    resp = client.post("/v1/devices", content=raw, headers={"Content-Type": "application/json"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("length", [16, 128])
def test_install_id_length_bounds(client: TestClient, length: int) -> None:
    status, _ = _register(client, uuid.uuid4().hex.ljust(length, "a")[:length])
    assert status == 201


def test_me_with_valid_token(client: TestClient) -> None:
    _, body = _register(client, _install_id())
    status, me = _me(client, body["device_token"])
    assert status == 200
    assert me == {"kind": "device", "id": body["device_id"]}


def test_old_token_still_valid_after_reregistration(client: TestClient) -> None:
    install_id = _install_id()
    _, first = _register(client, install_id)
    _register(client, install_id)
    assert _me(client, first["device_token"])[0] == 200


def test_me_without_token(client: TestClient) -> None:
    resp = client.get("/v1/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_required"


def _sign(claims: dict[str, object], secret: str = DEV_DEVICE_TOKEN_SECRET) -> str:
    return jwt.encode(claims, secret, algorithm="HS256")


def _bad_tokens(device_id: str) -> dict[str, str]:
    now = int(datetime.now(UTC).timestamp())
    good = {"sub": device_id, "typ": "device", "iat": now, "exp": now + 3600}
    return {
        "forged": _sign(good, secret="a" * 40),
        "expired": _sign({**good, "iat": now - 7200, "exp": now - 3600}),
        "wrong_typ": _sign({**good, "typ": "user"}),
        "unknown_device": _sign({**good, "sub": str(new_id())}),
    }


@pytest.mark.parametrize("case", ["forged", "expired", "wrong_typ", "unknown_device"])
def test_invalid_token(client: TestClient, case: str, caplog: pytest.LogCaptureFixture) -> None:
    _, body = _register(client, _install_id())
    token = _bad_tokens(body["device_id"])[case]
    with caplog.at_level("DEBUG"):
        resp = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_token"
    assert token not in resp.text
    assert token not in caplog.text


def test_tokens_not_logged_on_success(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("DEBUG"):
        _, body = _register(client, _install_id())
        _me(client, body["device_token"])
    assert body["device_token"] not in caplog.text


def test_devices_migration_roundtrip(db_url: str) -> None:
    url = create_database(db_url, "cw_devices_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    try:
        command.upgrade(cfg, "0002")  # 0003 adds the users FK and index (test_link.py)
        insp = inspect(eng)
        assert "devices" in insp.get_table_names()
        cols = {c["name"]: c for c in insp.get_columns("devices")}
        assert set(cols) == {
            "id",
            "install_id_hash",
            "user_id",
            "created_at",
            "last_seen_at",
            "attestation_ok_at",
        }
        assert cols["user_id"]["nullable"] and cols["attestation_ok_at"]["nullable"]
        assert not cols["install_id_hash"]["nullable"]
        for name in ("created_at", "last_seen_at", "attestation_ok_at"):
            assert getattr(cols[name]["type"], "timezone", False), name
        assert insp.get_foreign_keys("devices") == []
        uniques = insp.get_unique_constraints("devices")
        assert [u["column_names"] for u in uniques] == [["install_id_hash"]]

        command.downgrade(cfg, "0001")
        assert "devices" not in inspect(eng).get_table_names()
    finally:
        eng.dispose()
