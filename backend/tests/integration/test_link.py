"""POST /v1/auth/link and user subjects (Story 1.2), against Postgres, with a fake verifier."""

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import jwt
import pytest
from alembic import command
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session, get_session_factory, make_engine
from app.core.errors import AppError
from app.core.firebase import get_firebase_verifier
from app.core.tokens import invalid_token
from app.main import create_app
from app.modules.identity import service
from tests.integration.pg import alembic_config, create_database

pytestmark = pytest.mark.integration

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
INVALID_UID = "reject-me"
type Calls = list[tuple[uuid.UUID, uuid.UUID]]


class FakeVerifier:
    """Trusts the token's sub, except INVALID_UID (stands in for a bad signature/aud/iss/exp)."""

    configured = True

    def __init__(self) -> None:
        self.seen: list[str] = []

    def verify(self, id_token: str) -> str:
        self.seen.append(id_token)
        uid = str(jwt.decode(id_token, options={"verify_signature": False})["sub"])
        if uid == INVALID_UID:
            raise invalid_token()
        return uid


def _id_token(uid: str) -> str:
    now = int(datetime.now(UTC).timestamp())
    claims = {"sub": uid, "iat": now, "exp": now + 3600, "email": "secret@example.com"}
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "k"})


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
    app.dependency_overrides[get_firebase_verifier] = FakeVerifier
    return TestClient(app)


@pytest.fixture
def hook_calls() -> Iterator[Calls]:
    calls: Calls = []

    def hook(session: Session, from_device_id: uuid.UUID, to_user_id: uuid.UUID) -> None:
        assert session.in_transaction()
        calls.append((from_device_id, to_user_id))

    service.register_transfer_hook(hook)
    yield calls
    service.unregister_transfer_hook(hook)


def _uid() -> str:
    return f"uid-{uuid.uuid4().hex}"


def _device(client: TestClient) -> tuple[str, str]:
    body = client.post("/v1/devices", json={"install_id": str(uuid.uuid4())}).json()
    return body["device_id"], body["device_token"]


def _link(
    client: TestClient, uid: str, device_token: str | None = None
) -> tuple[int, dict[str, Any]]:
    body = {} if device_token is None else {"device_token": device_token}
    resp = client.post(
        "/v1/auth/link", headers={"Authorization": f"Bearer {_id_token(uid)}"}, json=body
    )
    return resp.status_code, resp.json()


def _device_user(engine: Engine, device_id: str) -> uuid.UUID | None:
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT user_id FROM devices WHERE id = :id"), {"id": device_id}
        ).scalar_one()
    return value  # type: ignore[no-any-return]


def _user_count(engine: Engine, uid: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM users WHERE firebase_uid = :u"), {"u": uid}
            ).scalar_one()
        )


def test_first_link(client: TestClient, engine: Engine, hook_calls: Calls) -> None:
    device_id, device_token = _device(client)
    uid = _uid()
    status, body = _link(client, uid, device_token)
    assert status == 201
    assert set(body) == {"user_id"}
    user_id = uuid.UUID(body["user_id"])
    assert user_id.version == 7
    assert _device_user(engine, device_id) == user_id
    assert _user_count(engine, uid) == 1
    assert hook_calls == [(uuid.UUID(device_id), user_id)]


def test_repeat_link_is_idempotent(client: TestClient, engine: Engine, hook_calls: Calls) -> None:
    _, device_token = _device(client)
    uid = _uid()
    _, first = _link(client, uid, device_token)
    status, second = _link(client, uid, device_token)
    assert status == 200
    assert second == first
    assert _user_count(engine, uid) == 1
    assert len(hook_calls) == 1  # exactly once


def test_existing_user_new_device(client: TestClient, engine: Engine, hook_calls: Calls) -> None:
    uid = _uid()
    _, first_token = _device(client)
    _, first = _link(client, uid, first_token)
    device_id, device_token = _device(client)
    status, body = _link(client, uid, device_token)
    assert status == 200
    assert body == first
    assert _device_user(engine, device_id) == uuid.UUID(first["user_id"])
    assert hook_calls[-1] == (uuid.UUID(device_id), uuid.UUID(first["user_id"]))
    assert len(hook_calls) == 2


def test_device_of_another_user(client: TestClient, engine: Engine, hook_calls: Calls) -> None:
    device_id, device_token = _device(client)
    _, owner = _link(client, _uid(), device_token)
    other = _uid()
    status, body = _link(client, other, device_token)
    assert status == 409
    assert body["error"]["code"] == "device_already_linked"
    assert _device_user(engine, device_id) == uuid.UUID(owner["user_id"])
    assert _user_count(engine, other) == 0  # rolled back with the failed link
    assert len(hook_calls) == 1


def test_link_without_device_token(client: TestClient, engine: Engine, hook_calls: Calls) -> None:
    uid = _uid()
    status, first = _link(client, uid)
    assert status == 201
    status, again = _link(client, uid)
    assert status == 200
    assert again == first
    assert hook_calls == []


def test_link_without_body(client: TestClient) -> None:
    resp = client.post("/v1/auth/link", headers={"Authorization": f"Bearer {_id_token(_uid())}"})
    assert resp.status_code == 201


def test_link_with_invalid_device_token(client: TestClient, engine: Engine) -> None:
    uid = _uid()
    status, body = _link(client, uid, "not-a-device-token")
    assert status == 401
    assert body["error"]["code"] == "invalid_token"
    assert _user_count(engine, uid) == 0


def test_link_invalid_id_token(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    token = _id_token(INVALID_UID)
    with caplog.at_level("DEBUG"):
        resp = client.post("/v1/auth/link", headers={"Authorization": f"Bearer {token}"}, json={})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_token"
    assert token not in resp.text
    assert token not in caplog.text


def test_link_with_device_token_as_bearer(client: TestClient) -> None:
    _, device_token = _device(client)
    resp = client.post(
        "/v1/auth/link", headers={"Authorization": f"Bearer {device_token}"}, json={}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_token"


def test_hook_failure_rolls_back(client: TestClient, engine: Engine) -> None:
    def failing(session: Session, from_device_id: uuid.UUID, to_user_id: uuid.UUID) -> None:
        raise RuntimeError("transfer failed")

    service.register_transfer_hook(failing)
    try:
        device_id, device_token = _device(client)
        uid = _uid()
        resp = TestClient(client.app, raise_server_exceptions=False).post(
            "/v1/auth/link",
            headers={"Authorization": f"Bearer {_id_token(uid)}"},
            json={"device_token": device_token},
        )
        assert resp.status_code == 500
    finally:
        service.unregister_transfer_hook(failing)
    assert _device_user(engine, device_id) is None
    assert _user_count(engine, uid) == 0


def test_me_as_linked_user(client: TestClient) -> None:
    uid = _uid()
    _, body = _link(client, uid)
    resp = client.get("/v1/me", headers={"Authorization": f"Bearer {_id_token(uid)}"})
    assert resp.status_code == 200
    assert resp.json() == {"kind": "user", "id": body["user_id"]}


def test_me_not_linked(client: TestClient) -> None:
    resp = client.get("/v1/me", headers={"Authorization": f"Bearer {_id_token(_uid())}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "not_linked"


def test_me_deleted_user(client: TestClient, engine: Engine) -> None:
    uid = _uid()
    _link(client, uid)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET deleted_at = now() WHERE firebase_uid = :u"), {"u": uid}
        )
    resp = client.get("/v1/me", headers={"Authorization": f"Bearer {_id_token(uid)}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_token"
    status, body = _link(client, uid)
    assert status == 401
    assert body["error"]["code"] == "invalid_token"


def test_device_token_still_works_after_link(client: TestClient) -> None:
    device_id, device_token = _device(client)
    _link(client, _uid(), device_token)
    resp = client.get("/v1/me", headers={"Authorization": f"Bearer {device_token}"})
    assert resp.json() == {"kind": "device", "id": device_id}


def test_users_table_stores_only_firebase_uid(client: TestClient, engine: Engine) -> None:
    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    assert cols == {"id", "firebase_uid", "created_at", "deleted_at"}
    uid = _uid()
    _link(client, uid)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM users WHERE firebase_uid = :u"), {"u": uid}).one()
    assert "secret@example.com" not in {str(v) for v in row}


def test_users_migration_roundtrip(db_url: str) -> None:
    url = create_database(db_url, "cw_users_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    try:
        command.upgrade(cfg, "0003")
        insp = inspect(eng)
        assert "users" in insp.get_table_names()
        cols = {c["name"]: c for c in insp.get_columns("users")}
        assert not cols["firebase_uid"]["nullable"]
        assert cols["deleted_at"]["nullable"]
        assert [u["column_names"] for u in insp.get_unique_constraints("users")] == [
            ["firebase_uid"]
        ]
        fks = insp.get_foreign_keys("devices")
        assert [(f["constrained_columns"], f["referred_table"]) for f in fks] == [
            (["user_id"], "users")
        ]
        assert fks[0]["options"].get("ondelete") == "SET NULL"
        assert ["user_id"] in [i["column_names"] for i in insp.get_indexes("devices")]

        command.downgrade(cfg, "0002")
        insp = inspect(eng)
        assert "users" not in insp.get_table_names()
        assert insp.get_foreign_keys("devices") == []
        assert ["user_id"] not in [i["column_names"] for i in insp.get_indexes("devices")]
    finally:
        eng.dispose()


def test_full_migration_roundtrip(db_url: str) -> None:
    url = create_database(db_url, "cw_full_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    try:
        command.upgrade(cfg, "head")
        assert {"users", "devices"} <= set(inspect(eng).get_table_names())
        command.downgrade(cfg, "base")
        assert set(inspect(eng).get_table_names()) <= {"alembic_version"}
        with eng.connect() as conn:
            exts = conn.execute(text("SELECT extname FROM pg_extension")).scalars().all()
        assert set(exts) == {"plpgsql"}
        command.upgrade(cfg, "head")  # and back up again
        assert {"users", "devices"} <= set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


# --- concurrency: two links at once, each with its own session --------------------------


def _run_concurrently(engine: Engine, calls: list[Callable[[Session], object]]) -> list[object]:
    """Run each call in its own thread and session, released together. Returns the result,
    or the AppError status, or the unexpected exception, per call."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    barrier = threading.Barrier(len(calls))
    results: list[object] = [None] * len(calls)

    def worker(i: int) -> None:
        with factory() as session:
            barrier.wait()
            try:
                results[i] = calls[i](session)
            except AppError as exc:
                results[i] = exc.status
            except Exception as exc:
                results[i] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(calls))]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    return results


@pytest.fixture
def slow_hook() -> Iterator[Calls]:
    """A hook that holds the link transaction open a moment, so the two links overlap."""
    calls: Calls = []
    lock = threading.Lock()

    def hook(session: Session, from_device_id: uuid.UUID, to_user_id: uuid.UUID) -> None:
        time.sleep(0.3)
        with lock:
            calls.append((from_device_id, to_user_id))

    service.register_transfer_hook(hook)
    yield calls
    service.unregister_transfer_hook(hook)


def test_concurrent_links_of_one_device_to_two_users(
    client: TestClient, engine: Engine, slow_hook: Calls
) -> None:
    device_id, device_token = _device(client)
    uids = [_uid(), _uid()]
    results = _run_concurrently(
        engine, [lambda s, u=u: service.link(s, u, device_token) for u in uids]
    )

    wins = [r for r in results if isinstance(r, tuple)]
    assert len(wins) == 1, results
    assert results.count(409) == 1, results
    winner_id, created = wins[0]  # type: ignore[misc]
    assert created is True
    assert slow_hook == [(uuid.UUID(device_id), winner_id)]
    assert _device_user(engine, device_id) == winner_id
    loser = uids[results.index(409)]
    assert _user_count(engine, loser) == 0


def test_concurrent_links_of_one_new_user(
    client: TestClient, engine: Engine, slow_hook: Calls
) -> None:
    uid = _uid()
    tokens = [_device(client)[1], _device(client)[1]]
    results = _run_concurrently(engine, [lambda s, t=t: service.link(s, uid, t) for t in tokens])

    assert all(isinstance(r, tuple) for r in results), results  # both 2xx, no 500
    user_ids = {r[0] for r in results}  # type: ignore[index]
    assert len(user_ids) == 1
    assert sorted(r[1] for r in results) == [False, True]  # type: ignore[index]
    assert _user_count(engine, uid) == 1
    assert len(slow_hook) == 2
