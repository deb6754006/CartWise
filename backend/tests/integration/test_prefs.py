"""The default range and /v1/me/prefs (Story 1.5), against Postgres, with a fake verifier."""

import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session, get_session_factory, make_engine
from app.core.firebase import get_firebase_verifier
from app.main import create_app
from app.modules.identity import service
from tests.integration.pg import alembic_config, create_database
from tests.integration.test_clubs import _bearer, _device, _link, _uid_of, _user
from tests.integration.test_link import FakeVerifier, _id_token

pytestmark = pytest.mark.integration

DEFAULT = {"default_mode": "car", "default_minutes": 15}
WALK_10 = {"default_mode": "walk", "default_minutes": 10}
CAR_20 = {"default_mode": "car", "default_minutes": 20}


@pytest.fixture(scope="module")
def prefs_url(db_url: str) -> str:
    """A database of its own: these tests truncate and count rows."""
    url = create_database(db_url, "cw_prefs")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(prefs_url: str) -> Iterator[Engine]:
    eng = make_engine(prefs_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE user_prefs, devices, users"))
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


def _get(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.get("/v1/me/prefs", headers=headers)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _put(client: TestClient, headers: dict[str, str], prefs: dict[str, Any]) -> None:
    resp = client.put("/v1/me/prefs", headers=headers, json=prefs)
    assert resp.status_code == 200, resp.text
    assert resp.json() == prefs


def _id_of(client: TestClient, headers: dict[str, str]) -> uuid.UUID:
    return uuid.UUID(client.get("/v1/me", headers=headers).json()["id"])


def _row_count(engine: Engine, subject_id: uuid.UUID | None = None) -> int:
    sql = "SELECT count(*) FROM user_prefs"
    params: dict[str, Any] = {}
    if subject_id is not None:
        sql += " WHERE subject_id = :id"
        params["id"] = subject_id
    with engine.connect() as conn:
        count: int = conn.execute(text(sql), params).scalar_one()
    return count


# --- reading and saving -----------------------------------------------------------------


def test_no_row_gives_the_system_default_and_creates_nothing(
    client: TestClient, engine: Engine
) -> None:
    _, headers = _device(client)
    assert _get(client, headers) == DEFAULT
    assert _row_count(engine) == 0


def test_put_saves_and_get_returns_it(client: TestClient) -> None:
    _, headers = _device(client)
    _put(client, headers, WALK_10)
    assert _get(client, headers) == WALK_10


def test_saving_again_updates_the_same_row(client: TestClient, engine: Engine) -> None:
    _, headers = _device(client)
    _put(client, headers, WALK_10)
    _put(client, headers, CAR_20)
    assert _get(client, headers) == CAR_20
    assert _row_count(engine) == 1


@pytest.mark.parametrize("mode", ["walk", "car"])
@pytest.mark.parametrize("minutes", [5, 10, 15, 20, 30])
def test_every_allowed_value_is_accepted(client: TestClient, mode: str, minutes: int) -> None:
    _, headers = _device(client)
    prefs = {"default_mode": mode, "default_minutes": minutes}
    _put(client, headers, prefs)
    assert _get(client, headers) == prefs


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"default_mode": "transit", "default_minutes": 10}, id="transit"),
        pytest.param({"default_mode": "WALK", "default_minutes": 10}, id="wrong-case"),
        pytest.param({"default_mode": "walk", "default_minutes": 7}, id="seven-minutes"),
        pytest.param({"default_mode": "walk", "default_minutes": 0}, id="zero-minutes"),
        pytest.param({"default_mode": "walk", "default_minutes": "10"}, id="minutes-as-text"),
        pytest.param({"default_mode": "walk", "default_minutes": True}, id="minutes-as-bool"),
        pytest.param({"default_mode": "walk", "default_minutes": None}, id="null-minutes"),
        pytest.param({"default_mode": "walk"}, id="no-minutes"),
        pytest.param({"default_minutes": 10}, id="no-mode"),
        pytest.param({}, id="empty"),
        pytest.param({"default_mode": "walk", "default_minutes": 10, "lat": 31.7}, id="location"),
        pytest.param(
            {"default_mode": "walk", "default_minutes": 10, "min_coverage_pct": 60},
            id="coverage",
        ),
    ],
)
def test_invalid_body_is_422_and_changes_nothing(
    client: TestClient, body: dict[str, Any], engine: Engine
) -> None:
    _, headers = _device(client)
    _put(client, headers, CAR_20)
    resp = client.put("/v1/me/prefs", headers=headers, json=body)
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert set(error) == {"code", "message_he", "details"}
    assert error["code"] == "validation_error"
    assert error["message_he"]
    assert _get(client, headers) == CAR_20
    assert _row_count(engine) == 1


def test_invalid_body_on_a_new_subject_creates_no_row(client: TestClient, engine: Engine) -> None:
    _, headers = _device(client)
    resp = client.put(
        "/v1/me/prefs",
        headers=headers,
        json={"default_mode": "transit", "default_minutes": 10},
    )
    assert resp.status_code == 422
    assert _row_count(engine) == 0


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_no_token_is_auth_required(client: TestClient, method: str) -> None:
    resp = client.request(method, "/v1/me/prefs", json=WALK_10 if method == "PUT" else None)
    assert resp.status_code == 401
    error = resp.json()["error"]
    assert error["code"] == "auth_required"
    assert error["message_he"]


def test_subjects_are_isolated(client: TestClient) -> None:
    _, first = _device(client)
    _, second = _device(client)
    user = _user(client)
    _put(client, first, WALK_10)
    assert _get(client, second) == DEFAULT
    assert _get(client, user) == DEFAULT
    _put(client, second, CAR_20)
    _put(client, user, {"default_mode": "walk", "default_minutes": 5})
    assert _get(client, first) == WALK_10
    assert _get(client, second) == CAR_20
    assert _get(client, user) == {"default_mode": "walk", "default_minutes": 5}


# --- what Epic 5 and Onboarding build on ------------------------------------------------


def test_prefs_for_subject_returns_what_was_saved(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    _, headers = _device(client)
    _put(client, headers, WALK_10)
    with factory() as session:
        prefs = service.prefs_for_subject(session, _id_of(client, headers))
    assert (prefs.default_mode, prefs.default_minutes) == ("walk", 10)


def test_prefs_for_subject_without_a_saved_range_is_car_15(
    client: TestClient, engine: Engine, factory: sessionmaker[Session]
) -> None:
    _, headers = _device(client)
    with factory() as session:
        prefs = service.prefs_for_subject(session, _id_of(client, headers))
    assert (prefs.default_mode, prefs.default_minutes) == ("car", 15)
    assert _row_count(engine) == 0


# --- moving the range on link -----------------------------------------------------------


def test_link_user_without_a_range_gets_the_devices(client: TestClient, engine: Engine) -> None:
    device_token, device = _device(client)
    _put(client, device, WALK_10)
    device_id = _id_of(client, device)
    user = _user(client, device_token)
    assert _get(client, user) == WALK_10
    assert _row_count(engine, device_id) == 0
    assert _row_count(engine) == 1


def test_link_existing_user_with_no_range_gets_the_devices(
    client: TestClient, engine: Engine
) -> None:
    user = _user(client)
    device_token, device = _device(client)
    _put(client, device, WALK_10)
    device_id = _id_of(client, device)
    assert _link(client, _uid_of(user), device_token)[0] == 200
    assert _get(client, user) == WALK_10
    assert _row_count(engine, device_id) == 0


def test_link_user_with_a_range_keeps_it(client: TestClient, engine: Engine) -> None:
    user = _user(client)
    _put(client, user, CAR_20)
    device_token, device = _device(client)
    _put(client, device, WALK_10)
    device_id = _id_of(client, device)
    assert _link(client, _uid_of(user), device_token)[0] == 200
    assert _get(client, user) == CAR_20
    assert _row_count(engine, device_id) == 0
    assert _row_count(engine) == 1


def test_link_of_a_device_with_no_range_changes_nothing(client: TestClient, engine: Engine) -> None:
    user = _user(client)
    _put(client, user, CAR_20)
    device_token, _ = _device(client)
    assert _link(client, _uid_of(user), device_token)[0] == 200
    assert _get(client, user) == CAR_20
    assert _row_count(engine) == 1


def test_repeat_link_applies_to_a_range_saved_as_a_guest(
    client: TestClient, engine: Engine
) -> None:
    # The device belongs to this user. The first link moved its range; the next ones find the
    # user with a range of its own, and only clear the device's row.
    device_token, device = _device(client)
    _put(client, device, WALK_10)
    device_id = _id_of(client, device)
    user = _user(client, device_token)
    _put(client, device, CAR_20)
    assert _row_count(engine, device_id) == 1
    assert _link(client, _uid_of(user), device_token)[0] == 200
    assert _get(client, user) == WALK_10
    assert _row_count(engine, device_id) == 0
    assert _link(client, _uid_of(user), device_token)[0] == 200
    assert _get(client, user) == WALK_10


def test_repeat_link_moves_the_range_when_the_user_has_none(
    client: TestClient, engine: Engine
) -> None:
    # The first link had no range to move, so the user still has none at the repeat link.
    device_token, device = _device(client)
    user = _user(client, device_token)
    _put(client, device, WALK_10)
    device_id = _id_of(client, device)
    assert _link(client, _uid_of(user), device_token)[0] == 200
    assert _get(client, user) == WALK_10
    assert _row_count(engine, device_id) == 0


def test_device_of_another_user_moves_nothing(client: TestClient, engine: Engine) -> None:
    device_token, device = _device(client)
    owner = _user(client, device_token)
    _put(client, device, WALK_10)
    other = _user(client)
    _put(client, other, CAR_20)
    status, body = _link(client, _uid_of(other), device_token)
    assert status == 409
    assert body["error"]["code"] == "device_already_linked"
    assert _get(client, device) == WALK_10
    assert _get(client, other) == CAR_20
    assert _get(client, owner) == DEFAULT
    assert _row_count(engine) == 2


def test_failure_in_link_rolls_back_the_move(client: TestClient, engine: Engine) -> None:
    def failing(session: Session, from_device_id: uuid.UUID, to_user_id: uuid.UUID) -> None:
        raise RuntimeError("transfer failed")

    device_token, device = _device(client)
    _put(client, device, WALK_10)
    uid = f"uid-{uuid.uuid4().hex}"
    service.register_transfer_hook(failing)
    try:
        resp = TestClient(client.app, raise_server_exceptions=False).post(
            "/v1/auth/link",
            headers=_bearer(_id_token(uid)),
            json={"device_token": device_token},
        )
    finally:
        service.unregister_transfer_hook(failing)
    assert resp.status_code == 500
    assert _get(client, device) == WALK_10
    assert _row_count(engine) == 1
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 0


def test_concurrent_put_and_link_do_not_lose_the_range(
    client: TestClient, engine: Engine, factory: sessionmaker[Session]
) -> None:
    device_token, device = _device(client)
    _put(client, device, WALK_10)
    device_id = _id_of(client, device)
    user = _user(client)

    # Link pauses after deleting the device's row, before giving its values to the user. A PUT
    # of the device arriving there has to wait, and then saves a row of its own.
    in_window = threading.Event()
    put_finished = threading.Event()
    put_got_through: list[bool] = []
    errors: list[Exception] = []

    def pause_link(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        if threading.current_thread() is linker and statement.startswith("INSERT INTO user_prefs"):
            in_window.set()
            put_got_through.append(put_finished.wait(timeout=1))

    def do_link() -> None:
        with factory() as session:
            try:
                service.link(session, _uid_of(user), device_token)
            except Exception as exc:
                errors.append(exc)

    def do_put() -> None:
        in_window.wait(timeout=10)
        with factory() as session:
            try:
                service.set_prefs(session, device_id, "car", 20)
            except Exception as exc:
                errors.append(exc)
        put_finished.set()

    linker = threading.Thread(target=do_link, daemon=True)
    putter = threading.Thread(target=do_put, daemon=True)
    event.listen(engine, "before_cursor_execute", pause_link)
    try:
        linker.start()
        putter.start()
        linker.join(timeout=30)
        putter.join(timeout=30)
    finally:
        event.remove(engine, "before_cursor_execute", pause_link)

    assert not linker.is_alive(), "link is stuck"
    assert not putter.is_alive(), "PUT is stuck"
    assert errors == []
    assert in_window.is_set()
    assert put_got_through == [False], "the PUT did not wait for the link"
    assert _get(client, user) == WALK_10
    assert _get(client, device) == CAR_20


def test_link_waits_for_a_first_put_in_progress(
    client: TestClient, engine: Engine, factory: sessionmaker[Session]
) -> None:
    device_token, device = _device(client)
    device_id = _id_of(client, device)
    user = _user(client)

    # The device's first PUT pauses after its INSERT, before its commit. A link arriving there
    # sees no row. It has to wait for the commit, or the choice would stay on the device.
    in_window = threading.Event()
    link_finished = threading.Event()
    link_got_through: list[bool] = []
    errors: list[Exception] = []

    def pause_put(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        if threading.current_thread() is putter and statement.startswith("INSERT INTO user_prefs"):
            in_window.set()
            link_got_through.append(link_finished.wait(timeout=1))

    def do_put() -> None:
        with factory() as session:
            try:
                service.set_prefs(session, device_id, "walk", 10)
            except Exception as exc:
                errors.append(exc)

    def do_link() -> None:
        in_window.wait(timeout=10)
        with factory() as session:
            try:
                service.link(session, _uid_of(user), device_token)
            except Exception as exc:
                errors.append(exc)
        link_finished.set()

    putter = threading.Thread(target=do_put, daemon=True)
    linker = threading.Thread(target=do_link, daemon=True)
    event.listen(engine, "after_cursor_execute", pause_put)
    try:
        putter.start()
        linker.start()
        putter.join(timeout=30)
        linker.join(timeout=30)
    finally:
        event.remove(engine, "after_cursor_execute", pause_put)

    assert not putter.is_alive(), "PUT is stuck"
    assert not linker.is_alive(), "link is stuck"
    assert errors == []
    assert in_window.is_set()
    assert link_got_through == [False], "the link did not wait for the PUT"
    # As if the PUT came first and the link after it.
    assert _get(client, user) == WALK_10
    assert _row_count(engine, device_id) == 0


def test_concurrent_puts_end_in_one_of_them(
    client: TestClient, engine: Engine, factory: sessionmaker[Session]
) -> None:
    _, headers = _device(client)
    subject = _id_of(client, headers)
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def worker(prefs: dict[str, Any]) -> None:
        with factory() as session:
            barrier.wait()
            try:
                service.set_prefs(session, subject, prefs["default_mode"], prefs["default_minutes"])
            except Exception as exc:
                errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(prefs,), daemon=True) for prefs in (WALK_10, CAR_20)
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    assert not any(th.is_alive() for th in threads), "a thread is stuck"
    assert errors == []
    assert _get(client, headers) in (WALK_10, CAR_20)
    assert _row_count(engine) == 1


# --- schema and migration ---------------------------------------------------------------


def test_schema_has_no_location_and_no_fk(engine: Engine) -> None:
    insp = inspect(engine)
    assert {c["name"] for c in insp.get_columns("user_prefs")} == {
        "subject_id",
        "default_mode",
        "default_minutes",
    }
    assert insp.get_pk_constraint("user_prefs")["constrained_columns"] == ["subject_id"]
    assert insp.get_foreign_keys("user_prefs") == []
    assert all(not c["nullable"] for c in insp.get_columns("user_prefs"))


@pytest.mark.parametrize(
    ("mode", "minutes", "constraint"),
    [
        pytest.param("transit", 10, "ck_user_prefs_default_mode", id="transit"),
        pytest.param("walk", 7, "ck_user_prefs_default_minutes", id="seven-minutes"),
    ],
)
def test_the_database_enforces_the_values(
    engine: Engine, mode: str, minutes: int, constraint: str
) -> None:
    insert = text(
        "INSERT INTO user_prefs (subject_id, default_mode, default_minutes)"
        " VALUES (:id, :mode, :minutes)"
    )
    # Never committed. The valid row shows the same INSERT fails only because of the value.
    with engine.connect() as conn:
        conn.execute(insert, {"id": uuid.uuid4(), "mode": "walk", "minutes": 10})
        with pytest.raises(IntegrityError, match=constraint):
            conn.execute(insert, {"id": uuid.uuid4(), "mode": mode, "minutes": minutes})


def test_models_match_the_migrations(prefs_url: str) -> None:
    command.check(alembic_config(prefs_url))  # raises when autogenerate would find a change


def test_prefs_migration_roundtrip_adds_no_data(db_url: str) -> None:
    url = create_database(db_url, "cw_prefs_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    try:
        command.upgrade(cfg, "0005")
        assert "user_prefs" not in inspect(eng).get_table_names()
        command.upgrade(cfg, "0006")
        with eng.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM user_prefs")).scalar_one() == 0
        command.downgrade(cfg, "0005")
        tables = set(inspect(eng).get_table_names())
        assert "user_prefs" not in tables
        assert {"user_brands", "user_clubs"} <= tables
    finally:
        eng.dispose()
