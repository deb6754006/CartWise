"""Brands, search and /v1/me/brands (Story 1.4), against Postgres, with a fake verifier."""

import threading
import unicodedata
import uuid
from collections.abc import Iterator
from typing import Any

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
from tests.integration.test_clubs import _bearer, _device, _link, _uid_of, _user
from tests.integration.test_link import FakeVerifier, _id_token

pytestmark = pytest.mark.integration

ZZZ = str(uuid.uuid4())  # never a real brand id
NAMES = ("מותג א׳", "מותג ב׳", "מותג ג׳")


@pytest.fixture(scope="module")
def brands_url(db_url: str) -> str:
    """A database of its own: these tests truncate the catalog and assert exact listings."""
    url = create_database(db_url, "cw_brands")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(brands_url: str) -> Iterator[Engine]:
    eng = make_engine(brands_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE promotion_products, promotions, price_observations, products, "
                "ingestion_alerts, "
                "ingestion_files, ingestion_runs, stores, user_brands, brands, "
                "user_clubs, clubs, chains, devices, users"
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


def _ensure(factory: sessionmaker[Session], *names: str) -> list[str]:
    with factory() as session:
        ids = [catalog_service.ensure_brand(session, name) for name in names]
        session.commit()
    return [str(i) for i in ids]


@pytest.fixture
def brands(factory: sessionmaker[Session]) -> list[str]:
    """Three brands, in name order: [a, b, c]."""
    return _ensure(factory, *NAMES)


def _search(client: TestClient, headers: dict[str, str], q: str) -> list[str]:
    resp = client.get("/v1/brands/search", headers=headers, params={"q": q})
    assert resp.status_code == 200, resp.text
    return [b["name"] for b in resp.json()]


def _get(client: TestClient, headers: dict[str, str]) -> set[str]:
    resp = client.get("/v1/me/brands", headers=headers)
    assert resp.status_code == 200
    ids = [b["id"] for b in resp.json()["brands"]]
    assert len(ids) == len(set(ids))
    return set(ids)


def _put(client: TestClient, headers: dict[str, str], *ids: str) -> set[str]:
    resp = client.put("/v1/me/brands", headers=headers, json={"brand_ids": list(ids)})
    assert resp.status_code == 200, resp.text
    return {b["id"] for b in resp.json()["brands"]}


# --- search -----------------------------------------------------------------------------


def test_search_returns_id_and_name(client: TestClient, brands: list[str]) -> None:
    _, headers = _device(client)
    resp = client.get("/v1/brands/search", headers=headers, params={"q": "מות"})
    assert resp.status_code == 200
    assert resp.json() == [{"id": i, "name": n} for i, n in zip(brands, NAMES, strict=True)]


def test_search_nothing_found(client: TestClient, brands: list[str]) -> None:
    _, headers = _device(client)
    assert _search(client, headers, "אין כזה") == []


def test_search_matches_a_substring_and_prefix_comes_first(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    _ensure(factory, "א מותג ב", "א מותג א", "מותג ת", "מותג ק", "בלי התאמה")
    _, headers = _device(client)
    assert _search(client, headers, "מותג") == ["מותג ק", "מותג ת", "א מותג א", "א מותג ב"]


def test_search_returns_at_most_20(client: TestClient, factory: sessionmaker[Session]) -> None:
    _ensure(factory, *(f"מותג {i:02}" for i in range(25)))
    _, headers = _device(client)
    assert _search(client, headers, "מותג") == [f"מותג {i:02}" for i in range(20)]


@pytest.mark.parametrize(
    "q",
    [
        pytest.param("מוּתָּג", id="niqqud"),
        pytest.param("מות׳ג", id="geresh"),
        pytest.param('מו"תג', id="gershayim"),
        pytest.param("  מותג  ", id="spaces"),
    ],
)
def test_search_ignores_niqqud_quotes_and_spaces(
    client: TestClient, factory: sessionmaker[Session], q: str
) -> None:
    _ensure(factory, "מותג טוב", "אחר")
    _, headers = _device(client)
    assert _search(client, headers, q) == _search(client, headers, "מותג") == ["מותג טוב"]


def test_search_matches_a_name_written_with_niqqud_and_quotes(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    _ensure(factory, "מוּתָּג ״טוב״  מאוד")
    _, headers = _device(client)
    assert _search(client, headers, "טוב מאוד") == ["מוּתָּג ״טוב״  מאוד"]


@pytest.mark.parametrize(
    ("name", "q"),
    [
        pytest.param("מותג-טוב", "מותג טוב", id="hyphen-in-name"),
        pytest.param("מותג\u05beטוב", "מותג טוב", id="maqaf-in-name"),
        pytest.param("מותג טוב", "מותג-טוב", id="hyphen-in-search"),
        pytest.param("מותג-טוב", "מותג\u05beטוב", id="hyphen-and-maqaf"),
    ],
)
def test_search_treats_hyphen_maqaf_and_space_alike(
    client: TestClient, factory: sessionmaker[Session], name: str, q: str
) -> None:
    _ensure(factory, name)
    _, headers = _device(client)
    assert _search(client, headers, q) == [name]


def test_search_ignores_invisible_format_characters(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    _ensure(factory, "\u200fמותג טוב\u200e")
    _, headers = _device(client)
    assert _search(client, headers, "\u202bמו\u200bתג\u202c") == ["\u200fמותג טוב\u200e"]
    assert _search(client, headers, "\u200fמ\u200f") == []


def test_search_is_case_insensitive_for_latin(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    _ensure(factory, "Brand X")
    _, headers = _device(client)
    assert _search(client, headers, "bRAND") == ["Brand X"]


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        pytest.param("%%", ["מותג 100%%"], id="percent"),
        pytest.param("__", ["מותג a__b"], id="underscore"),
        pytest.param("\\\\", ["מותג \\\\"], id="backslash"),
        pytest.param("%_\\", ["מותג %_\\"], id="all-together"),
        pytest.param("a%", [], id="percent-is-not-a-wildcard"),
        pytest.param("a_b", [], id="underscore-is-not-a-wildcard"),
    ],
)
def test_special_characters_are_plain(
    client: TestClient, factory: sessionmaker[Session], q: str, expected: list[str]
) -> None:
    _ensure(factory, "מותג 100%%", "מותג a__b", "מותג \\\\", "מותג %_\\", "מותג axb")
    _, headers = _device(client)
    assert _search(client, headers, q) == expected


@pytest.mark.parametrize(
    "q",
    [
        pytest.param("", id="empty"),
        pytest.param("מ", id="one-letter"),
        pytest.param(" מ ", id="one-letter-and-spaces"),
        pytest.param("מ׳", id="one-letter-after-normalizing"),
        pytest.param("׳״", id="nothing-after-normalizing"),
    ],
)
def test_short_search_is_an_empty_list(client: TestClient, brands: list[str], q: str) -> None:
    _, headers = _device(client)
    assert _search(client, headers, q) == []


def test_nul_in_search_finds_nothing(client: TestClient, brands: list[str]) -> None:
    _, headers = _device(client)
    assert _search(client, headers, "מו\x00ת") == []


def test_search_of_exactly_100_is_accepted(client: TestClient, brands: list[str]) -> None:
    _, headers = _device(client)
    assert _search(client, headers, "מ" * 100) == []


@pytest.mark.parametrize(
    "params",
    [pytest.param({"q": "מ" * 101}, id="over-100"), pytest.param({}, id="no-q")],
)
def test_bad_search_is_422(client: TestClient, params: dict[str, str]) -> None:
    _, headers = _device(client)
    resp = client.get("/v1/brands/search", headers=headers, params=params)
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert set(error) == {"code", "message_he", "details"}
    assert error["code"] == "validation_error"
    assert "מממ" not in resp.text


def test_search_text_is_not_logged(
    client: TestClient, brands: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    _, headers = _device(client)
    with caplog.at_level("DEBUG"):
        _search(client, headers, "מחרוזתסודית")
        client.get("/v1/brands/search", headers=headers, params={"q": "מחרוזתסודית" * 20})
    assert "מחרוזתסודית" not in caplog.text
    for record in caplog.records:
        assert "מחרוזתסודית" not in str(vars(record))


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/brands/search?q=abc"),
        ("GET", "/v1/me/brands"),
        ("PUT", "/v1/me/brands"),
    ],
)
def test_no_token_is_auth_required(client: TestClient, method: str, path: str) -> None:
    resp = client.request(method, path, json={"brand_ids": []} if method == "PUT" else None)
    assert resp.status_code == 401
    error = resp.json()["error"]
    assert error["code"] == "auth_required"
    assert error["message_he"]


# --- my brands --------------------------------------------------------------------------


def test_no_brands_is_an_empty_list(client: TestClient) -> None:
    _, headers = _device(client)
    resp = client.get("/v1/me/brands", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"brands": []}


def test_put_answers_sorted_by_name_and_get_matches(client: TestClient, brands: list[str]) -> None:
    a, b, c = brands
    _, headers = _device(client)
    resp = client.put("/v1/me/brands", headers=headers, json={"brand_ids": [c, a]})
    assert resp.status_code == 200
    assert resp.json() == {
        "brands": [{"id": a, "name": "מותג א׳"}, {"id": c, "name": "מותג ג׳"}],
    }
    assert client.get("/v1/me/brands", headers=headers).json() == resp.json()
    assert _put(client, headers, b) == {b}
    assert _get(client, headers) == {b}


def test_duplicate_ids_are_saved_once(client: TestClient, brands: list[str]) -> None:
    a = brands[0]
    _, headers = _device(client)
    resp = client.put("/v1/me/brands", headers=headers, json={"brand_ids": [a, a]})
    assert resp.status_code == 200
    assert resp.json() == {"brands": [{"id": a, "name": "מותג א׳"}]}
    assert _get(client, headers) == {a}


def test_empty_list_clears(client: TestClient, brands: list[str]) -> None:
    _, headers = _device(client)
    _put(client, headers, *brands)
    assert _put(client, headers) == set()
    assert _get(client, headers) == set()


def test_unknown_id_rejects_everything(client: TestClient, brands: list[str]) -> None:
    a, b, _ = brands
    _, headers = _device(client)
    _put(client, headers, b)
    resp = client.put("/v1/me/brands", headers=headers, json={"brand_ids": [a, ZZZ]})
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "unknown_brand"
    assert error["message_he"] == "אחד המותגים שנבחרו לא קיים"
    assert error["details"] == {"brand_ids": [ZZZ]}
    assert _get(client, headers) == {b}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(lambda a: {"brand_ids": [a], "extra": "12345"}, id="extra-field"),
        pytest.param(lambda a: {"brand_ids": [a, "not-a-uuid"]}, id="not-a-uuid"),
        pytest.param(lambda a: {"brand_ids": [a] * 201}, id="over-200"),
        pytest.param(lambda a: {}, id="missing-field"),
    ],
)
def test_invalid_body_saves_nothing(client: TestClient, brands: list[str], body: Any) -> None:
    a, b, _ = brands
    _, headers = _device(client)
    _put(client, headers, b)
    resp = client.put("/v1/me/brands", headers=headers, json=body(a))
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert set(error) == {"code", "message_he", "details"}
    assert error["code"] == "validation_error"
    assert _get(client, headers) == {b}


def test_exactly_200_ids_are_accepted(client: TestClient, factory: sessionmaker[Session]) -> None:
    ids = set(_ensure(factory, *(f"מותג {i}" for i in range(200))))
    assert len(ids) == 200
    _, headers = _device(client)
    assert _put(client, headers, *ids) == ids
    assert _get(client, headers) == ids


def test_subjects_are_isolated(client: TestClient, brands: list[str]) -> None:
    a, b, c = brands
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


def test_brand_ids_for_subject_returns_only_the_chosen_one(
    client: TestClient, brands: list[str], factory: sessionmaker[Session]
) -> None:
    # What Epics 2 and 5 build on.
    a = brands[0]
    _, headers = _device(client)
    _put(client, headers, a)
    subject = uuid.UUID(client.get("/v1/me", headers=headers).json()["id"])
    with factory() as session:
        assert service.brand_ids_for_subject(session, subject) == [uuid.UUID(a)]


def test_deleting_a_brand_removes_its_marks(
    client: TestClient, brands: list[str], engine: Engine
) -> None:
    a, b, _ = brands
    _, headers = _device(client)
    _put(client, headers, a, b)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM brands WHERE id = :id"), {"id": a})
    assert _get(client, headers) == {b}


def test_concurrent_puts_never_mix(
    client: TestClient, brands: list[str], factory: sessionmaker[Session]
) -> None:
    a, b, c = (uuid.UUID(i) for i in brands)
    _, headers = _device(client)
    subject = uuid.UUID(client.get("/v1/me", headers=headers).json()["id"])
    sets = [{a, b}, {b, c}]
    for _ in range(5):
        assert _set_concurrently(factory, subject, sets) == []
        with factory() as session:
            assert set(service.brand_ids_for_subject(session, subject)) in sets


def _set_concurrently(
    factory: sessionmaker[Session], subject: uuid.UUID, sets: list[set[uuid.UUID]]
) -> list[Exception]:
    barrier = threading.Barrier(len(sets))
    errors: list[Exception] = []

    def worker(ids: set[uuid.UUID]) -> None:
        with factory() as session:
            barrier.wait()
            try:
                service.set_brands(session, subject, ids)
            except Exception as exc:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,), daemon=True) for s in sets]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    assert not any(th.is_alive() for th in threads), "a thread is stuck (deadlock?)"
    return errors


# --- moving brands on link --------------------------------------------------------------


def test_first_link_moves_brands_to_the_new_user(client: TestClient, brands: list[str]) -> None:
    a = brands[0]
    device_token, device = _device(client)
    _put(client, device, a)
    user = _user(client, device_token)
    assert _get(client, user) == {a}
    assert _get(client, device) == set()


def test_link_to_existing_user_is_a_union(client: TestClient, brands: list[str]) -> None:
    a, b, c = brands
    user = _user(client)
    _put(client, user, b, c)
    device_token, device = _device(client)
    _put(client, device, a, b)
    status, _ = _link(client, _uid_of(user), device_token)
    assert status == 200
    assert _get(client, user) == {a, b, c}
    assert _get(client, device) == set()


def test_repeat_link_moves_brands_chosen_as_a_guest(client: TestClient, brands: list[str]) -> None:
    a, b, _ = brands
    device_token, device = _device(client)
    _put(client, device, a)
    user = _user(client, device_token)
    _put(client, device, b)
    assert _link(client, _uid_of(user), device_token)[0] == 200
    assert _get(client, user) == {a, b}
    assert _get(client, device) == set()
    assert _link(client, _uid_of(user), device_token)[0] == 200
    assert _get(client, user) == {a, b}


def test_device_of_another_user_moves_nothing(client: TestClient, brands: list[str]) -> None:
    a, b, _ = brands
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
    client: TestClient, brands: list[str], engine: Engine
) -> None:
    a = brands[0]

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
        total = conn.execute(text("SELECT count(*) FROM user_brands")).scalar_one()
        users = conn.execute(text("SELECT count(*) FROM users")).scalar_one()
    assert total == 1
    assert users == 0


def test_concurrent_put_and_link_do_not_lose_brands(
    client: TestClient, brands: list[str], engine: Engine, factory: sessionmaker[Session]
) -> None:
    a, b, c = brands
    device_token, device = _device(client)
    _put(client, device, a)
    device_id = uuid.UUID(client.get("/v1/me", headers=device).json()["id"])
    user = _user(client)
    _put(client, user, c)

    # As with clubs: link pauses between copying the device's brands and deleting them. A PUT
    # committed there would have its brands deleted without being copied. The lock keeps it out.
    in_window = threading.Event()
    put_finished = threading.Event()
    errors: list[Exception] = []

    def pause_link(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        if threading.current_thread() is linker and statement.startswith("DELETE FROM user_brands"):
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
                service.set_brands(session, device_id, {uuid.UUID(b)})
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


def test_concurrent_links_of_two_devices_with_clubs_and_brands_do_not_deadlock(
    client: TestClient, brands: list[str], factory: sessionmaker[Session]
) -> None:
    a, b, _ = brands
    first_token, first = _device(client)
    second_token, second = _device(client)
    _put(client, first, a)
    _put(client, second, b)
    user = _user(client)
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def do_link(token: str) -> None:
        with factory() as session:
            barrier.wait()
            try:
                service.link(session, _uid_of(user), token)
            except Exception as exc:
                errors.append(exc)

    threads = [
        threading.Thread(target=do_link, args=(token,), daemon=True)
        for token in (first_token, second_token)
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    assert not any(th.is_alive() for th in threads), "a thread is stuck (deadlock?)"
    assert errors == []
    assert _get(client, user) == {a, b}


# --- schema, migration, seed ------------------------------------------------------------


def test_schema_constraints(engine: Engine) -> None:
    insp = inspect(engine)
    assert {c["name"] for c in insp.get_columns("brands")} == {"id", "name", "name_norm"}
    assert {c["name"] for c in insp.get_columns("user_brands")} == {"subject_id", "brand_id"}
    assert insp.get_pk_constraint("user_brands")["constrained_columns"] == [
        "subject_id",
        "brand_id",
    ]
    fks = insp.get_foreign_keys("user_brands")
    assert [(f["constrained_columns"], f["referred_table"]) for f in fks] == [
        (["brand_id"], "brands")
    ]
    assert fks[0]["options"].get("ondelete") == "CASCADE"
    assert ["brand_id"] in [i["column_names"] for i in insp.get_indexes("user_brands")]
    assert ["name"] in [u["column_names"] for u in insp.get_unique_constraints("brands")]


def test_name_norm_has_a_trigram_index(engine: Engine) -> None:
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_brands_name_norm'")
        ).scalar_one()
    assert "USING gin" in definition
    assert "gin_trgm_ops" in definition


def test_models_match_the_migrations(brands_url: str) -> None:
    command.check(alembic_config(brands_url))  # raises when autogenerate would find a change


def test_brands_migration_roundtrip_adds_no_data(db_url: str) -> None:
    url = create_database(db_url, "cw_brands_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    try:
        command.upgrade(cfg, "0004")
        assert "brands" not in inspect(eng).get_table_names()
        command.upgrade(cfg, "0005")
        with eng.connect() as conn:
            for table in ("brands", "user_brands"):
                assert conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one() == 0  # noqa: S608
        command.downgrade(cfg, "0004")
        tables = set(inspect(eng).get_table_names())
        assert not tables & {"brands", "user_brands"}
        assert {"chains", "clubs", "user_clubs"} <= tables
    finally:
        eng.dispose()


def test_ensure_brand_stores_nfc_and_norm_and_dedupes(
    factory: sessionmaker[Session], engine: Engine
) -> None:
    not_nfc = "מותג \ufb2a"  # a precomposed presentation form, which NFC decomposes
    nfc = unicodedata.normalize("NFC", not_nfc)
    assert nfc != not_nfc
    with factory() as session:
        first = catalog_service.ensure_brand(session, not_nfc)
        second = catalog_service.ensure_brand(session, nfc)
        session.commit()
    assert first == second
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name, name_norm FROM brands")).all()
    assert [tuple(row) for row in rows] == [(nfc, "מותג ש")]


def test_seed_is_idempotent(client: TestClient, factory: sessionmaker[Session]) -> None:
    with factory() as session:
        seed_dev_catalog.seed(session)
    _, headers = _device(client)
    first = client.get("/v1/brands/search", headers=headers, params={"q": "מותג"}).json()
    assert [b["name"] for b in first] == list(NAMES)
    with factory() as session:
        seed_dev_catalog.seed(session)
    assert client.get("/v1/brands/search", headers=headers, params={"q": "מותג"}).json() == first


def test_seed_main_runs_in_dev(
    monkeypatch: pytest.MonkeyPatch, brands_url: str, client: TestClient
) -> None:
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", brands_url)
    get_settings.cache_clear()
    try:
        assert seed_dev_catalog.main() == 0
    finally:
        get_settings.cache_clear()
    _, headers = _device(client)
    assert _search(client, headers, "מותג") == list(NAMES)


def test_seed_refuses_in_prod(
    monkeypatch: pytest.MonkeyPatch, brands_url: str, client: TestClient
) -> None:
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("DATABASE_URL", brands_url)
    monkeypatch.setenv("DEVICE_TOKEN_SECRET", "x" * 40)
    get_settings.cache_clear()
    try:
        assert seed_dev_catalog.main() == 1
    finally:
        get_settings.cache_clear()
    _, headers = _device(client)
    assert _search(client, headers, "מותג") == []
