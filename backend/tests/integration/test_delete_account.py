"""DELETE /v1/me and purge_deleted (Story 1.7), against Postgres, with a fake verifier."""

import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session, get_session_factory, make_engine
from app.core.errors import AppError
from app.core.firebase import get_firebase_verifier
from app.main import create_app
from app.modules.catalog import service as catalog_service
from app.modules.identity import repository, service
from app.modules.identity.service import PurgeResult
from app.worker.jobs import purge_deleted as purge_job
from tests.integration.pg import alembic_config, create_database
from tests.integration.test_clubs import _bearer, _device, _link
from tests.integration.test_link import FakeVerifier, _id_token, _run_concurrently

pytestmark = pytest.mark.integration

WALK_10 = {"default_mode": "walk", "default_minutes": 10}
type Calls = list[uuid.UUID]
PAST = service.PURGE_AFTER + timedelta(hours=1)  # due for purge
NOT_YET = service.PURGE_AFTER - timedelta(hours=1)  # not due yet
# How long a paused write waits for a delete it may be blocking (then goes on).
PAUSE_S = 1.0


@pytest.fixture(scope="module")
def delete_url(db_url: str) -> str:
    """A database of its own: these tests truncate and count rows."""
    url = create_database(db_url, "cw_delete")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(delete_url: str) -> Iterator[Engine]:
    eng = make_engine(delete_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE product_aliases, promotion_products, promotions, "
                "price_observations, products, "
                "ingestion_alerts, "
                "ingestion_files, ingestion_runs, stores, user_clubs, user_brands, "
                "user_prefs, clubs, chains, brands, devices, users"
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def client(engine: Engine, factory: sessionmaker[Session]) -> TestClient:
    app = create_app(engine=engine)

    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_firebase_verifier] = FakeVerifier
    return TestClient(app)


@pytest.fixture
def catalog(factory: sessionmaker[Session]) -> tuple[str, str]:
    """(club_id, brand_id)."""
    with factory() as session:
        club = catalog_service.ensure_chain_with_club(session, "רשת א׳", "מועדון א׳")
        brand = catalog_service.ensure_brand(session, "תנובה")
        session.commit()
    return str(club), str(brand)


@pytest.fixture
def deletion_calls() -> Iterator[Calls]:
    calls: Calls = []

    def hook(session: Session, user_id: uuid.UUID) -> None:
        assert session.in_transaction()
        calls.append(user_id)

    service.register_deletion_hook(hook)
    yield calls
    service.unregister_deletion_hook(hook)


@pytest.fixture
def purge_calls() -> Iterator[Calls]:
    calls: Calls = []

    def hook(session: Session, user_id: uuid.UUID) -> None:
        assert session.in_transaction()
        calls.append(user_id)

    service.register_purge_hook(hook)
    yield calls
    service.unregister_purge_hook(hook)


class _Account:
    """A linked user with a device, clubs, brands and a range."""

    def __init__(self, client: TestClient, catalog: tuple[str, str]) -> None:
        self.uid = f"uid-{uuid.uuid4().hex}"
        self.device_token, self.device = _device(client)
        status, body = _link(client, self.uid, self.device_token)
        assert status == 201
        self.user_id = uuid.UUID(body["user_id"])
        self.headers = _bearer(_id_token(self.uid))
        club, brand = catalog
        for path, body_ in (
            ("/v1/me/clubs", {"club_ids": [club]}),
            ("/v1/me/brands", {"brand_ids": [brand]}),
            ("/v1/me/prefs", WALK_10),
        ):
            resp = client.put(path, headers=self.headers, json=body_)
            assert resp.status_code == 200, resp.text


def _count(engine: Engine, table: str, subject_id: uuid.UUID) -> int:
    column = "id" if table == "users" else "subject_id"
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :s"),  # noqa: S608
                {"s": subject_id},
            ).scalar_one()
        )


def _user_row(engine: Engine, user_id: uuid.UUID) -> tuple[str, datetime | None]:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT firebase_uid, deleted_at FROM users WHERE id = :id"), {"id": user_id}
        ).one()
    return row[0], row[1]


def _linked_devices(engine: Engine, user_id: uuid.UUID) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM devices WHERE user_id = :id"), {"id": user_id}
            ).scalar_one()
        )


def _identity_rows(engine: Engine, user_id: uuid.UUID) -> int:
    return sum(_count(engine, t, user_id) for t in ("user_clubs", "user_brands", "user_prefs"))


def _delete(client: TestClient, headers: dict[str, str]) -> int:
    resp = client.delete("/v1/me", headers=headers)
    if resp.status_code == 204:
        assert resp.content == b""
    return resp.status_code


def _set_deleted_at(engine: Engine, user_id: uuid.UUID, when: datetime) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET deleted_at = :w WHERE id = :id"), {"w": when, "id": user_id}
        )


# --- DELETE /v1/me ----------------------------------------------------------------------


def test_delete(
    client: TestClient, engine: Engine, catalog: tuple[str, str], deletion_calls: Calls
) -> None:
    account = _Account(client, catalog)
    assert _identity_rows(engine, account.user_id) == 3
    assert _linked_devices(engine, account.user_id) == 1

    assert _delete(client, account.headers) == 204

    firebase_uid, deleted_at = _user_row(engine, account.user_id)
    assert deleted_at is not None
    assert firebase_uid == f"deleted:{account.user_id}"
    assert _linked_devices(engine, account.user_id) == 0
    assert _identity_rows(engine, account.user_id) == 0
    assert deletion_calls == [account.user_id]


def test_guest_is_account_required(
    client: TestClient, engine: Engine, catalog: tuple[str, str], deletion_calls: Calls
) -> None:
    club, _ = catalog
    _, device = _device(client)
    assert client.put("/v1/me/clubs", headers=device, json={"club_ids": [club]}).is_success
    device_id = uuid.UUID(client.get("/v1/me", headers=device).json()["id"])

    resp = client.delete("/v1/me", headers=device)
    assert resp.status_code == 403
    assert resp.json() == {
        "error": {
            "code": "account_required",
            "message_he": service.ACCOUNT_REQUIRED_HE,
            "details": {},
        }
    }
    assert _count(engine, "user_clubs", device_id) == 1
    assert deletion_calls == []


def test_no_token_is_auth_required(client: TestClient) -> None:
    resp = client.delete("/v1/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_required"


def test_token_after_delete_is_not_linked(
    client: TestClient, catalog: tuple[str, str], deletion_calls: Calls
) -> None:
    account = _Account(client, catalog)
    assert _delete(client, account.headers) == 204
    for method, path in (("GET", "/v1/me"), ("DELETE", "/v1/me"), ("GET", "/v1/me/clubs")):
        resp = client.request(method, path, headers=account.headers)
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "not_linked"
    assert deletion_calls == [account.user_id]  # the second DELETE never reached the service


def test_register_again_makes_a_new_empty_user(
    client: TestClient, engine: Engine, catalog: tuple[str, str]
) -> None:
    account = _Account(client, catalog)
    assert _delete(client, account.headers) == 204

    status, body = _link(client, account.uid, account.device_token)
    assert status == 201
    new_id = uuid.UUID(body["user_id"])
    assert new_id != account.user_id
    assert _linked_devices(engine, new_id) == 1
    assert client.get("/v1/me", headers=account.headers).json() == {
        "kind": "user",
        "id": str(new_id),
    }
    assert client.get("/v1/me/clubs", headers=account.headers).json() == {"club_ids": []}
    assert client.get("/v1/me/brands", headers=account.headers).json() == {"brands": []}
    assert client.get("/v1/me/prefs", headers=account.headers).json() == {
        "default_mode": "car",
        "default_minutes": 15,
    }


def test_device_after_delete_is_a_guest(client: TestClient, catalog: tuple[str, str]) -> None:
    account = _Account(client, catalog)
    device_id = client.get("/v1/me", headers=account.device).json()["id"]
    assert _delete(client, account.headers) == 204

    assert client.get("/v1/me", headers=account.device).json() == {
        "kind": "device",
        "id": device_id,
    }
    resp = client.put("/v1/me/prefs", headers=account.device, json=WALK_10)
    assert resp.status_code == 200
    # A guest still cannot delete anything.
    assert client.delete("/v1/me", headers=account.device).status_code == 403


def test_other_user_is_untouched(
    client: TestClient, engine: Engine, catalog: tuple[str, str]
) -> None:
    gone = _Account(client, catalog)
    kept = _Account(client, catalog)
    assert _delete(client, gone.headers) == 204

    assert _user_row(engine, kept.user_id) == (kept.uid, None)
    assert _linked_devices(engine, kept.user_id) == 1
    assert _identity_rows(engine, kept.user_id) == 3
    assert client.get("/v1/me", headers=kept.headers).json()["id"] == str(kept.user_id)


def test_failing_hook_rolls_everything_back(
    client: TestClient, engine: Engine, catalog: tuple[str, str]
) -> None:
    account = _Account(client, catalog)

    def boom(session: Session, user_id: uuid.UUID) -> None:
        raise RuntimeError("hook failed")

    service.register_deletion_hook(boom)
    try:
        resp = client.delete("/v1/me", headers=account.headers)
    finally:
        service.unregister_deletion_hook(boom)
    assert resp.status_code == 500
    assert set(resp.json()["error"]) == {"code", "message_he", "details"}

    assert _user_row(engine, account.user_id) == (account.uid, None)
    assert _linked_devices(engine, account.user_id) == 1
    assert _identity_rows(engine, account.user_id) == 3
    assert client.get("/v1/me", headers=account.headers).status_code == 200


def test_hook_registration_is_idempotent(client: TestClient, catalog: tuple[str, str]) -> None:
    calls: Calls = []

    def hook(session: Session, user_id: uuid.UUID) -> None:
        calls.append(user_id)

    assert service.register_deletion_hook(hook) is hook
    service.register_deletion_hook(hook)
    try:
        account = _Account(client, catalog)
        assert _delete(client, account.headers) == 204
    finally:
        service.unregister_deletion_hook(hook)
    assert calls == [account.user_id]


# --- purge_deleted ----------------------------------------------------------------------


def test_purge_removes_only_users_past_purge_after(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    catalog: tuple[str, str],
    purge_calls: Calls,
) -> None:
    now = datetime.now(UTC)
    old = _Account(client, catalog)
    recent = _Account(client, catalog)
    alive = _Account(client, catalog)
    for account in (old, recent):
        assert _delete(client, account.headers) == 204
    _set_deleted_at(engine, old.user_id, now - PAST)
    _set_deleted_at(engine, recent.user_id, now - NOT_YET)

    with factory() as session:
        assert service.purge_deleted(session, now) == PurgeResult(purged=1, failed=0)

    assert _count(engine, "users", old.user_id) == 0
    assert _count(engine, "users", recent.user_id) == 1
    assert _count(engine, "users", alive.user_id) == 1
    assert purge_calls == [old.user_id]
    # The device of the purged user is still there, as a guest.
    assert client.get("/v1/me", headers=old.device).json()["kind"] == "device"

    # A second run changes nothing.
    with factory() as session:
        assert service.purge_deleted(session, now) == PurgeResult(purged=0, failed=0)
    assert purge_calls == [old.user_id]
    assert _count(engine, "users", recent.user_id) == 1


def test_purge_hook_failure_rolls_back_that_user_only(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    catalog: tuple[str, str],
) -> None:
    now = datetime.now(UTC)
    first = _Account(client, catalog)
    second = _Account(client, catalog)
    for i, account in enumerate((first, second)):
        assert _delete(client, account.headers) == 204
        _set_deleted_at(engine, account.user_id, now - PAST - timedelta(days=2 - i))

    def flaky(session: Session, user_id: uuid.UUID) -> None:
        if user_id == first.user_id:
            raise RuntimeError("hook failed")

    service.register_purge_hook(flaky)
    try:
        with factory() as session:
            assert service.purge_deleted(session, now) == PurgeResult(purged=1, failed=1)
    finally:
        service.unregister_purge_hook(flaky)

    assert _count(engine, "users", first.user_id) == 1  # retried on the next run
    assert _count(engine, "users", second.user_id) == 0

    with factory() as session:
        assert service.purge_deleted(session, now) == PurgeResult(purged=1, failed=0)
    assert _count(engine, "users", first.user_id) == 0


def test_worker_job_runs_purge_with_its_own_session(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    catalog: tuple[str, str],
    purge_calls: Calls,
) -> None:
    account = _Account(client, catalog)
    assert _delete(client, account.headers) == 204
    _set_deleted_at(engine, account.user_id, datetime.now(UTC) - PAST)

    assert purge_job.run(session_factory=factory) == PurgeResult(purged=1, failed=0)
    assert purge_calls == [account.user_id]
    assert purge_job.run(session_factory=factory) == PurgeResult(purged=0, failed=0)


def test_purge_after_keeps_the_30_day_promise() -> None:
    # The job runs once a day: a row due at PURGE_AFTER is gone by PURGE_AFTER + 1 day.
    assert service.PURGE_AFTER + timedelta(days=1) <= timedelta(days=30)


def test_purge_deletes_leftover_identity_rows(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], catalog: tuple[str, str]
) -> None:
    account = _Account(client, catalog)
    assert _delete(client, account.headers) == 204
    club, brand = catalog
    with engine.begin() as conn:  # rows written after the delete (the race the locks stop)
        conn.execute(
            text("INSERT INTO user_clubs (subject_id, club_id) VALUES (:s, :c)"),
            {"s": account.user_id, "c": club},
        )
        conn.execute(
            text("INSERT INTO user_brands (subject_id, brand_id) VALUES (:s, :b)"),
            {"s": account.user_id, "b": brand},
        )
        conn.execute(
            text(
                "INSERT INTO user_prefs (subject_id, default_mode, default_minutes) "
                "VALUES (:s, 'walk', 10)"
            ),
            {"s": account.user_id},
        )
    assert _identity_rows(engine, account.user_id) == 3
    now = datetime.now(UTC)
    _set_deleted_at(engine, account.user_id, now - PAST)

    with factory() as session:
        assert service.purge_deleted(session, now) == PurgeResult(purged=1, failed=0)
    assert _identity_rows(engine, account.user_id) == 0
    assert _count(engine, "users", account.user_id) == 0


def test_two_deletes_at_once_both_succeed(
    client: TestClient, engine: Engine, catalog: tuple[str, str], deletion_calls: Calls
) -> None:
    account = _Account(client, catalog)
    results = _run_concurrently(
        engine, [lambda s: service.delete_account(s, account.user_id) for _ in range(2)]
    )
    assert results == [None, None]
    assert deletion_calls == [account.user_id]  # the second one changed nothing
    assert _user_row(engine, account.user_id)[0] == f"deleted:{account.user_id}"


def test_delete_of_an_already_deleted_user_is_a_no_op(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], catalog: tuple[str, str]
) -> None:
    account = _Account(client, catalog)
    assert _delete(client, account.headers) == 204
    before = _user_row(engine, account.user_id)
    with factory() as session:
        service.delete_account(session, account.user_id)  # no error
    assert _user_row(engine, account.user_id) == before


def _pause_before(
    monkeypatch: pytest.MonkeyPatch, name: str, reached: threading.Event, done: threading.Event
) -> None:
    """Make repository.<name> signal `reached`, then wait (at most PAUSE_S) for `done`."""
    original: Callable[..., object] = getattr(repository, name)

    def paused(*args: object, **kwargs: object) -> object:
        reached.set()
        done.wait(PAUSE_S)
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, name, paused)


def _delete_after(
    reached: threading.Event, done: threading.Event, user_id: uuid.UUID
) -> Callable[[Session], object]:
    def call(session: Session) -> object:
        assert reached.wait(10)
        try:
            return service.delete_account(session, user_id)
        finally:
            done.set()

    return call


@pytest.mark.parametrize(
    ("write", "paused_fn"),
    [
        ("clubs", "replace_user_clubs"),
        ("brands", "replace_user_brands"),
        ("prefs", "upsert_user_prefs"),
    ],
)
def test_put_against_a_delete_leaves_no_rows(
    client: TestClient,
    engine: Engine,
    catalog: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    write: str,
    paused_fn: str,
) -> None:
    """The PUT has seen the user alive and is about to write when the delete starts.

    The user row lock (FOR SHARE) makes the delete wait for the PUT, and then delete what it
    wrote. Without it, the delete would commit first, and the PUT's row would stay forever.
    """
    account = _Account(client, catalog)
    club, brand = catalog
    user_id = account.user_id
    writes: dict[str, Callable[[Session], object]] = {
        "clubs": lambda s: service.set_clubs(s, user_id, [uuid.UUID(club)]),
        "brands": lambda s: service.set_brands(s, user_id, [uuid.UUID(brand)]),
        "prefs": lambda s: service.set_prefs(s, user_id, "car", 20),
    }
    reached, done = threading.Event(), threading.Event()
    _pause_before(monkeypatch, paused_fn, reached, done)

    results = _run_concurrently(engine, [writes[write], _delete_after(reached, done, user_id)])

    assert results[1] is None, results
    assert not isinstance(results[0], Exception), results
    assert _identity_rows(engine, user_id) == 0


def test_put_after_a_delete_is_invalid_token(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], catalog: tuple[str, str]
) -> None:
    account = _Account(client, catalog)
    assert _delete(client, account.headers) == 204
    with factory() as session, pytest.raises(AppError) as exc:
        service.set_prefs(session, account.user_id, "car", 20)
    assert exc.value.code == "invalid_token"
    assert exc.value.status == 401
    assert _identity_rows(engine, account.user_id) == 0


def test_concurrent_link_and_delete_leave_no_device_linked(
    client: TestClient, engine: Engine, catalog: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A link of a new device has found the user, and is about to lock the device, when the
    delete starts. Either the link sees the deletion (401), or it ends first and the delete
    then unlinks its device. Without the FOR SHARE in link, the delete would commit in that
    gap, and the device would stay linked to the deleted user."""
    account = _Account(client, catalog)
    device_token, _ = _device(client)
    reached, done = threading.Event(), threading.Event()
    _pause_before(monkeypatch, "lock_device", reached, done)

    results = _run_concurrently(
        engine,
        [
            lambda s: service.link(s, account.uid, device_token),
            _delete_after(reached, done, account.user_id),
        ],
    )

    assert results[1] is None, results
    assert results[0] == 401 or results[0] == (account.user_id, False), results
    assert _linked_devices(engine, account.user_id) == 0
