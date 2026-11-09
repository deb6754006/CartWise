"""Chains, clubs and /v1/me/clubs (Story 1.3), against Postgres, with a fake verifier."""

import threading
import unicodedata
import uuid
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.db import get_session, get_session_factory, make_engine
from app.core.firebase import get_firebase_verifier
from app.main import create_app
from app.modules.catalog import service as catalog_service
from app.modules.identity import service
from scripts import seed_dev_catalog
from tests.integration.pg import alembic_config, create_database
from tests.integration.test_link import FakeVerifier, _id_token

pytestmark = pytest.mark.integration

ZZZ = str(uuid.uuid4())  # never a real club id


@pytest.fixture(scope="module")
def clubs_url(db_url: str) -> str:
    """A database of its own: these tests truncate the catalog and assert exact listings."""
    url = create_database(db_url, "cw_clubs")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(clubs_url: str) -> Iterator[Engine]:
    eng = make_engine(clubs_url)
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
                "ingestion_files, ingestion_runs, stores, user_clubs, clubs, chains, "
                "devices, users"
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
def clubs(factory: sessionmaker[Session]) -> list[str]:
    """Three clubs of three chains, in chain-name order: [a, b, c]."""
    with factory() as session:
        ids = [
            catalog_service.ensure_chain_with_club(session, chain, f"מועדון {chain}")
            for chain in ("רשת א׳", "רשת ב׳", "רשת ג׳")
        ]
        session.commit()
    return [str(i) for i in ids]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _device(client: TestClient) -> tuple[str, dict[str, str]]:
    body = client.post("/v1/devices", json={"install_id": str(uuid.uuid4())}).json()
    return body["device_token"], _bearer(body["device_token"])


def _link(client: TestClient, uid: str, device_token: str | None = None) -> tuple[int, Any]:
    body = {} if device_token is None else {"device_token": device_token}
    resp = client.post("/v1/auth/link", headers=_bearer(_id_token(uid)), json=body)
    return resp.status_code, resp.json()


def _user(client: TestClient, device_token: str | None = None) -> dict[str, str]:
    uid = f"uid-{uuid.uuid4().hex}"
    assert _link(client, uid, device_token)[0] in (200, 201)
    return _bearer(_id_token(uid))


def _get(client: TestClient, headers: dict[str, str]) -> set[str]:
    resp = client.get("/v1/me/clubs", headers=headers)
    assert resp.status_code == 200
    ids = resp.json()["club_ids"]
    assert len(ids) == len(set(ids))
    return set(ids)


def _put(client: TestClient, headers: dict[str, str], *ids: str) -> set[str]:
    resp = client.put("/v1/me/clubs", headers=headers, json={"club_ids": list(ids)})
    assert resp.status_code == 200, resp.text
    return set(resp.json()["club_ids"])


# --- chains and clubs -------------------------------------------------------------------


def test_chains_and_clubs_are_empty_without_data(client: TestClient) -> None:
    _, headers = _device(client)
    assert client.get("/v1/chains", headers=headers).json() == []
    assert client.get("/v1/clubs", headers=headers).json() == []


def test_chains_sorted_by_name(client: TestClient, factory: sessionmaker[Session]) -> None:
    with factory() as session:
        for chain in ("רשת ג׳", "רשת א׳", "רשת ב׳"):
            catalog_service.ensure_chain_with_club(session, chain, "מועדון")
        session.commit()
    _, headers = _device(client)
    resp = client.get("/v1/chains", headers=headers)
    assert resp.status_code == 200
    assert [c["name"] for c in resp.json()] == ["רשת א׳", "רשת ב׳", "רשת ג׳"]
    assert all(set(c) == {"id", "name"} for c in resp.json())


def test_clubs_sorted_by_chain_then_club(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    pairs = [("רשת ב׳", "ב"), ("רשת א׳", "ג"), ("רשת ב׳", "א"), ("רשת א׳", "ד")]
    with factory() as session:
        for chain, club in pairs:
            catalog_service.ensure_chain_with_club(session, chain, club)
        session.commit()
    _, headers = _device(client)
    resp = client.get("/v1/clubs", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert [(c["chain_name"], c["name"]) for c in body] == [
        ("רשת א׳", "ג"),
        ("רשת א׳", "ד"),
        ("רשת ב׳", "א"),
        ("רשת ב׳", "ב"),
    ]
    assert all(set(c) == {"id", "name", "chain_id", "chain_name"} for c in body)
    assert body[0]["chain_id"] == body[1]["chain_id"] != body[2]["chain_id"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/chains"),
        ("GET", "/v1/clubs"),
        ("GET", "/v1/me/clubs"),
        ("PUT", "/v1/me/clubs"),
    ],
)
def test_no_token_is_auth_required(client: TestClient, method: str, path: str) -> None:
    resp = client.request(method, path, json={"club_ids": []} if method == "PUT" else None)
    assert resp.status_code == 401
    error = resp.json()["error"]
    assert error["code"] == "auth_required"
    assert error["message_he"]


# --- my clubs ---------------------------------------------------------------------------


def test_no_marks_is_an_empty_list(client: TestClient) -> None:
    _, headers = _device(client)
    resp = client.get("/v1/me/clubs", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"club_ids": []}


def test_put_replaces_the_set(client: TestClient, clubs: list[str]) -> None:
    a, b, c = clubs
    _, headers = _device(client)
    assert _put(client, headers, a, b) == {a, b}
    assert _get(client, headers) == {a, b}
    assert _put(client, headers, c) == {c}
    assert _get(client, headers) == {c}


def test_duplicate_ids_are_saved_once(client: TestClient, clubs: list[str]) -> None:
    a = clubs[0]
    _, headers = _device(client)
    resp = client.put("/v1/me/clubs", headers=headers, json={"club_ids": [a, a]})
    assert resp.status_code == 200
    assert resp.json() == {"club_ids": [a]}
    assert _get(client, headers) == {a}


def test_empty_list_clears(client: TestClient, clubs: list[str]) -> None:
    _, headers = _device(client)
    _put(client, headers, *clubs)
    assert _put(client, headers) == set()
    assert _get(client, headers) == set()


def test_unknown_id_rejects_everything(client: TestClient, clubs: list[str]) -> None:
    a, b, _ = clubs
    _, headers = _device(client)
    _put(client, headers, b)
    resp = client.put("/v1/me/clubs", headers=headers, json={"club_ids": [a, ZZZ]})
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "unknown_club"
    assert error["message_he"] == "אחד המועדונים שנבחרו לא קיים"
    assert error["details"] == {"club_ids": [ZZZ]}
    assert _get(client, headers) == {b}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(lambda a: {"club_ids": [a], "member_number": "12345"}, id="extra-field"),
        pytest.param(lambda a: {"club_ids": [a, "not-a-uuid"]}, id="not-a-uuid"),
        pytest.param(lambda a: {"club_ids": [a] * 201}, id="over-200"),
        pytest.param(lambda a: {}, id="missing-field"),
    ],
)
def test_invalid_body_saves_nothing(client: TestClient, clubs: list[str], body: Any) -> None:
    a, b, _ = clubs
    _, headers = _device(client)
    _put(client, headers, b)
    resp = client.put("/v1/me/clubs", headers=headers, json=body(a))
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert set(error) == {"code", "message_he", "details"}
    assert error["code"] == "validation_error"
    assert "12345" not in resp.text
    assert _get(client, headers) == {b}


def test_exactly_200_ids_are_accepted(client: TestClient, factory: sessionmaker[Session]) -> None:
    with factory() as session:
        ids = {
            str(catalog_service.ensure_chain_with_club(session, "רשת א׳", f"מועדון {i}"))
            for i in range(200)
        }
        session.commit()
    assert len(ids) == 200
    _, headers = _device(client)
    assert _put(client, headers, *ids) == ids
    assert _get(client, headers) == ids


def test_subjects_are_isolated(client: TestClient, clubs: list[str]) -> None:
    a, b, c = clubs
    _, first = _device(client)
    _, second = _device(client)
    user = _user(client)
    _put(client, first, a)
    _put(client, second, b)
    _put(client, user, c)
    assert _get(client, first) == {a}
    assert _get(client, second) == {b}
    assert _get(client, user) == {c}
    _put(client, first)
    assert _get(client, second) == {b}
    assert _get(client, user) == {c}


def test_club_ids_for_subject_returns_only_the_marked_one(
    client: TestClient, clubs: list[str], factory: sessionmaker[Session]
) -> None:
    # What Epic 5 builds on: a club of another chain is not returned unless it is marked.
    a = clubs[0]
    _, headers = _device(client)
    _put(client, headers, a)
    subject = uuid.UUID(client.get("/v1/me", headers=headers).json()["id"])
    with factory() as session:
        assert service.club_ids_for_subject(session, subject) == [uuid.UUID(a)]


def test_deleting_a_club_removes_its_marks(
    client: TestClient, clubs: list[str], engine: Engine
) -> None:
    a, b, _ = clubs
    _, headers = _device(client)
    _put(client, headers, a, b)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM clubs WHERE id = :id"), {"id": a})
    assert _get(client, headers) == {b}


def test_concurrent_puts_never_mix(
    client: TestClient, clubs: list[str], factory: sessionmaker[Session]
) -> None:
    a, b, c = (uuid.UUID(i) for i in clubs)
    _, headers = _device(client)
    subject = uuid.UUID(client.get("/v1/me", headers=headers).json()["id"])
    sets = [{a, b}, {b, c}]
    for _ in range(5):
        assert _set_concurrently(factory, subject, sets) == []
        with factory() as session:
            assert set(service.club_ids_for_subject(session, subject)) in sets


def _set_concurrently(
    factory: sessionmaker[Session], subject: uuid.UUID, sets: list[set[uuid.UUID]]
) -> list[Exception]:
    barrier = threading.Barrier(len(sets))
    errors: list[Exception] = []

    def worker(ids: set[uuid.UUID]) -> None:
        with factory() as session:
            barrier.wait()
            try:
                service.set_clubs(session, subject, ids)
            except Exception as exc:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,), daemon=True) for s in sets]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    assert not any(th.is_alive() for th in threads), "a thread is stuck (deadlock?)"
    return errors


# --- moving marks on link ---------------------------------------------------------------


def test_first_link_moves_marks_to_the_new_user(client: TestClient, clubs: list[str]) -> None:
    a = clubs[0]
    device_token, device = _device(client)
    _put(client, device, a)
    user = _user(client, device_token)
    assert _get(client, user) == {a}
    assert _get(client, device) == set()


def test_link_to_existing_user_is_a_union(client: TestClient, clubs: list[str]) -> None:
    a, b, c = clubs
    user = _user(client)
    _put(client, user, b, c)
    device_token, device = _device(client)
    _put(client, device, a, b)
    uid = _uid_of(user)
    status, _ = _link(client, uid, device_token)
    assert status == 200
    assert _get(client, user) == {a, b, c}
    assert _get(client, device) == set()


def test_repeat_link_moves_marks_made_as_a_guest(client: TestClient, clubs: list[str]) -> None:
    a, b, _ = clubs
    device_token, device = _device(client)
    _put(client, device, a)
    user = _user(client, device_token)
    # Signed out: the device token again, and new marks as a guest.
    _put(client, device, b)
    status, _ = _link(client, _uid_of(user), device_token)
    assert status == 200
    assert _get(client, user) == {a, b}
    assert _get(client, device) == set()
    # And once more, with nothing left to move: no change.
    assert _link(client, _uid_of(user), device_token)[0] == 200
    assert _get(client, user) == {a, b}


def test_device_of_another_user_moves_nothing(client: TestClient, clubs: list[str]) -> None:
    a, b, _ = clubs
    device_token, device = _device(client)
    owner = _user(client, device_token)
    _put(client, device, a)
    other = _user(client)
    _put(client, other, b)
    status, body = _link(client, _uid_of(other), device_token)
    assert status == 409
    assert body["error"]["code"] == "device_already_linked"
    assert _get(client, device) == {a}
    assert _get(client, other) == {b}
    assert _get(client, owner) == set()


def test_failure_in_link_rolls_back_the_move(
    client: TestClient, clubs: list[str], engine: Engine
) -> None:
    a = clubs[0]

    def failing(session: Session, from_device_id: uuid.UUID, to_user_id: uuid.UUID) -> None:
        raise RuntimeError("transfer failed")

    device_token, device = _device(client)
    _put(client, device, a)
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
    assert _get(client, device) == {a}
    with engine.connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM user_clubs")).scalar_one()
        users = conn.execute(text("SELECT count(*) FROM users")).scalar_one()
    assert total == 1
    assert users == 0


def test_concurrent_put_and_link_do_not_lose_marks(
    client: TestClient, clubs: list[str], engine: Engine, factory: sessionmaker[Session]
) -> None:
    a, b, c = clubs
    device_token, device = _device(client)
    _put(client, device, a)
    device_id = uuid.UUID(client.get("/v1/me", headers=device).json()["id"])
    user = _user(client)
    _put(client, user, c)

    # The window that matters is inside the move, between copying the device's marks and
    # deleting them: a PUT committed there would have its marks deleted without being copied.
    # So link pauses there, giving the PUT time to finish. The lock must keep it out.
    in_window = threading.Event()
    put_finished = threading.Event()
    errors: list[Exception] = []

    def pause_link(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        if threading.current_thread() is linker and statement.startswith("DELETE FROM user_clubs"):
            in_window.set()
            put_finished.wait(timeout=1)

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
                service.set_clubs(session, device_id, {uuid.UUID(b)})
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
    put_then_link = ({b, c}, set())
    link_then_put = ({a, c}, {b})
    assert (_get(client, user), _get(client, device)) in (put_then_link, link_then_put)


def _uid_of(headers: dict[str, str]) -> str:
    token = headers["Authorization"].removeprefix("Bearer ")
    return str(jwt.decode(token, options={"verify_signature": False})["sub"])


# --- schema, migration, seed ------------------------------------------------------------


def test_no_member_number_anywhere(engine: Engine) -> None:
    insp = inspect(engine)
    assert {c["name"] for c in insp.get_columns("user_clubs")} == {"subject_id", "club_id"}
    assert {c["name"] for c in insp.get_columns("clubs")} == {"id", "chain_id", "name"}


def test_schema_constraints(engine: Engine) -> None:
    insp = inspect(engine)
    assert insp.get_pk_constraint("user_clubs")["constrained_columns"] == [
        "subject_id",
        "club_id",
    ]
    fks = insp.get_foreign_keys("user_clubs")
    assert [(f["constrained_columns"], f["referred_table"]) for f in fks] == [
        (["club_id"], "clubs")
    ]
    assert fks[0]["options"].get("ondelete") == "CASCADE"
    assert ["club_id"] in [i["column_names"] for i in insp.get_indexes("user_clubs")]
    assert ["chain_id", "name"] in [u["column_names"] for u in insp.get_unique_constraints("clubs")]
    assert ["gov_chain_code"] in [u["column_names"] for u in insp.get_unique_constraints("chains")]
    cols = {c["name"]: c for c in insp.get_columns("chains")}
    assert cols["gov_chain_code"]["nullable"]


def test_models_match_the_migrations(clubs_url: str) -> None:
    command.check(alembic_config(clubs_url))  # raises when autogenerate would find a change


def test_clubs_migration_roundtrip_adds_no_data(db_url: str) -> None:
    url = create_database(db_url, "cw_clubs_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    try:
        command.upgrade(cfg, "0003")
        assert "chains" not in inspect(eng).get_table_names()
        command.upgrade(cfg, "0004")
        with eng.connect() as conn:
            for table in ("chains", "clubs", "user_clubs"):
                assert conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one() == 0  # noqa: S608
        command.downgrade(cfg, "0003")
        tables = set(inspect(eng).get_table_names())
        assert not tables & {"chains", "clubs", "user_clubs"}
        assert {"users", "devices"} <= tables
    finally:
        eng.dispose()


def test_ensure_chain_with_club_stores_nfc_and_dedupes(
    factory: sessionmaker[Session], engine: Engine
) -> None:
    not_nfc = "רשת \ufb2a"  # a precomposed presentation form, which NFC decomposes
    nfc = unicodedata.normalize("NFC", not_nfc)
    assert nfc != not_nfc
    with factory() as session:
        first = catalog_service.ensure_chain_with_club(session, not_nfc, not_nfc)
        second = catalog_service.ensure_chain_with_club(session, nfc, nfc)
        session.commit()
    assert first == second
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM chains")).scalars().all() == [nfc]
        assert conn.execute(text("SELECT name FROM clubs")).scalars().all() == [nfc]


def test_seed_is_idempotent(client: TestClient, factory: sessionmaker[Session]) -> None:
    with factory() as session:
        seed_dev_catalog.seed(session)
    _, headers = _device(client)
    first = client.get("/v1/clubs", headers=headers).json()
    assert [c["name"] for c in first] == ["מועדון רשת א׳", "מועדון רשת ב׳", "מועדון רשת ג׳"]
    with factory() as session:
        seed_dev_catalog.seed(session)
    assert client.get("/v1/clubs", headers=headers).json() == first
    assert len(client.get("/v1/chains", headers=headers).json()) == 3


def test_seed_main_runs_in_dev(
    monkeypatch: pytest.MonkeyPatch, clubs_url: str, factory: sessionmaker[Session]
) -> None:
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", clubs_url)
    get_settings.cache_clear()
    try:
        assert seed_dev_catalog.main() == 0
    finally:
        get_settings.cache_clear()
    with factory() as session:
        assert len(catalog_service.list_clubs(session)) == 3


def test_seed_refuses_in_prod(
    monkeypatch: pytest.MonkeyPatch,
    clubs_url: str,
    factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("DATABASE_URL", clubs_url)
    monkeypatch.setenv("DEVICE_TOKEN_SECRET", "x" * 40)
    get_settings.cache_clear()
    try:
        assert seed_dev_catalog.main() == 1
    finally:
        get_settings.cache_clear()
    assert "ENV=prod" in capsys.readouterr().err
    with factory() as session:
        assert catalog_service.list_chains(session) == []
