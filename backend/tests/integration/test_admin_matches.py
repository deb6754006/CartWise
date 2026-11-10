"""The match admin tool (Story 4.5): /v1/admin and scripts/matches.py, against Postgres, with a
fake Firebase verifier. Every product, barcode, name, UID and price here is invented."""

import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_session, get_session_factory, make_engine
from app.core.firebase import get_firebase_verifier
from app.core.tokens import invalid_token
from app.main import create_app
from app.modules.catalog import service as catalog_service
from app.modules.catalog.service import ProductRecord
from app.modules.matching import service as matching_service
from app.modules.matching.service import FileItem
from scripts import matches as cli
from tests.integration.pg import alembic_config, create_database
from tests.integration.test_link import FakeVerifier, _id_token
from tests.integration.test_prices import (
    _item,
    _price_file,
    _prices,
    _promo_file,
    _promo_item,
    _promos,
    _promotion,
    _store,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
OPERATOR_UID = "operator-uid-fake"
UNLISTED_UID = "plain-user-uid-fake"
SETTINGS = Settings(OPERATOR_FIREBASE_UIDS=f" other-op , {OPERATOR_UID} ,")
_codes = iter(range(2 * 10**12, 3 * 10**12))


@pytest.fixture(scope="module")
def admin_url(db_url: str) -> str:
    """A database of its own: these tests truncate and count rows."""
    url = create_database(db_url, "cw_admin_matches")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(admin_url: str) -> Iterator[Engine]:
    eng = make_engine(admin_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE match_votes, match_candidates, product_aliases, promotion_products, "
                "promotions, price_observations, products, ingestion_alerts, ingestion_files, "
                "ingestion_runs, stores, user_clubs, user_brands, user_prefs, clubs, chains, "
                "devices, users"
            )
        )
        conn.execute(text("REFRESH MATERIALIZED VIEW current_prices"))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _client(engine: Engine, factory: sessionmaker[Session], verifier: Any = FakeVerifier) -> Any:
    app = create_app(engine=engine)

    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_firebase_verifier] = verifier
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    return TestClient(app)


@pytest.fixture
def client(engine: Engine, factory: sessionmaker[Session]) -> TestClient:
    return _client(engine, factory)  # type: ignore[no-any-return]


def _user(engine: Engine, firebase_uid: str | None = None, deleted: bool = False) -> uuid.UUID:
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, firebase_uid, deleted_at) VALUES (:id, :uid, :d)"),
            {
                "id": user_id,
                "uid": firebase_uid or f"uid-{user_id.hex}",
                "d": NOW if deleted else None,
            },
        )
    return user_id


@pytest.fixture
def operator(engine: Engine, factory: sessionmaker[Session]) -> uuid.UUID:
    return _user(engine, OPERATOR_UID)


def _auth(uid: str = OPERATOR_UID) -> dict[str, str]:
    return {"Authorization": f"Bearer {_id_token(uid)}"}


@pytest.fixture
def chain(factory: sessionmaker[Session]) -> uuid.UUID:
    chain_id, _ = _store(factory)
    return chain_id  # type: ignore[no-any-return]


def _product(factory: sessionmaker[Session], name: str = "מוצר בדוי") -> uuid.UUID:
    code = str(next(_codes))
    with factory() as session:
        ids = catalog_service.ensure_products_by_barcode(
            session, [ProductRecord(code, name, None, None, False)], now=NOW
        )
        session.commit()
    return ids[code]


def _proposed(
    factory: sessionmaker[Session], name: str, barcode: str | None = None, now: datetime = NOW
) -> uuid.UUID:
    with factory() as session:
        product_id = catalog_service.propose_product(
            session, name, None, None, barcode=barcode, now=now
        )
        session.commit()
    return product_id


def _alias(
    engine: Engine,
    chain_id: uuid.UUID,
    product_id: uuid.UUID | None,
    state: str = "uncertain",
    text_: str | None = None,
    barcode: str | None = None,
    occurrences: int = 0,
    confidence: Decimal | None = Decimal("0.6"),
    updated_at: datetime = NOW,
) -> uuid.UUID:
    alias_id = uuid.uuid4()
    name = text_ or f"כינוי {alias_id.hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO product_aliases (id, chain_id, alias_text, alias_norm, barcode, "
                "product_id, state, confidence, occurrences, created_at, updated_at) "
                "VALUES (:id, :chain, :t, :n, :b, :p, :s, :c, :o, :now, :u)"
            ),
            {
                "id": alias_id,
                "chain": chain_id,
                "t": name,
                "n": catalog_service.alias_norm(name),
                "b": barcode,
                "p": product_id,
                "s": state,
                "c": confidence,
                "o": occurrences,
                "now": NOW,
                "u": updated_at,
            },
        )
    return alias_id


def _candidates(engine: Engine, alias_id: uuid.UUID, *scored: tuple[uuid.UUID, str]) -> None:
    with engine.begin() as conn:
        for rank, (product_id, score) in enumerate(scored, start=1):
            conn.execute(
                text(
                    "INSERT INTO match_candidates (alias_id, rank, product_id, score, created_at) "
                    "VALUES (:a, :r, :p, :s, :now)"
                ),
                {"a": alias_id, "r": rank, "p": product_id, "s": Decimal(score), "now": NOW},
            )


def _rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql), params)]


def _one(engine: Engine, sql: str, **params: Any) -> dict[str, Any]:
    [row] = _rows(engine, sql, **params)
    return row


def _alias_row(engine: Engine, alias_id: uuid.UUID) -> dict[str, Any]:
    return _one(engine, "SELECT * FROM product_aliases WHERE id = :id", id=alias_id)


def _product_row(engine: Engine, product_id: uuid.UUID) -> dict[str, Any]:
    return _one(engine, "SELECT * FROM products WHERE id = :id", id=product_id)


# --- authorization ---

ENDPOINTS: list[tuple[str, str]] = [
    ("GET", "/v1/admin/matches/disputed"),
    ("GET", "/v1/admin/matches/uncertain"),
    ("GET", "/v1/admin/products/proposed"),
    ("POST", f"/v1/admin/matches/{uuid.uuid4()}/approve"),
    ("POST", f"/v1/admin/products/{uuid.uuid4()}/approve"),
    ("POST", "/v1/admin/products/merge"),
]


def _call(client: TestClient, method: str, path: str, headers: dict[str, str] | None = None) -> Any:
    if method == "GET":
        return client.get(path, headers=headers)
    body = {"keep_id": str(uuid.uuid4()), "remove_id": str(uuid.uuid4())}
    return client.post(path, headers=headers, json=body if path.endswith("merge") else None)


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_no_token_is_401(client: TestClient, method: str, path: str) -> None:
    resp = _call(client, method, path)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_required"


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_not_an_operator_is_403(client: TestClient, engine: Engine, method: str, path: str) -> None:
    _user(engine, UNLISTED_UID)
    resp = _call(client, method, path, _auth(UNLISTED_UID))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_device_token_is_403(client: TestClient) -> None:
    device = client.post("/v1/devices", json={"install_id": str(uuid.uuid4())}).json()
    resp = client.get(
        "/v1/admin/matches/uncertain",
        headers={"Authorization": f"Bearer {device['device_token']}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_listed_uid_with_no_user_or_deleted_is_403(client: TestClient, engine: Engine) -> None:
    resp = client.get("/v1/admin/matches/uncertain", headers=_auth())
    assert resp.status_code == 403
    _user(engine, OPERATOR_UID, deleted=True)
    resp = client.get("/v1/admin/matches/uncertain", headers=_auth())
    assert resp.status_code == 403


def test_unconfigured_sign_in_is_503(engine: Engine, factory: sessionmaker[Session]) -> None:
    class Unconfigured(FakeVerifier):
        configured = False

    client = _client(engine, factory, Unconfigured)
    resp = client.get("/v1/admin/matches/uncertain", headers=_auth())
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "auth_unavailable"


def test_operator_uids_setting() -> None:
    assert Settings(OPERATOR_FIREBASE_UIDS="").operator_firebase_uids == frozenset()
    assert Settings(OPERATOR_FIREBASE_UIDS=" a, ,b ,").operator_firebase_uids == {"a", "b"}
    assert Settings().operator_firebase_uids == frozenset()


# --- lists ---


def test_uncertain_queue_by_occurrences(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    a, b, c, d = (_product(factory, f"מוצר {n}") for n in "אבגד")
    five = _alias(engine, chain, a, occurrences=5, text_="כינוי חמש")
    one = _alias(engine, chain, a, occurrences=1, text_="כינוי אחת")
    nine = _alias(engine, chain, b, occurrences=9, text_="כינוי תשע")
    _alias(engine, chain, a, state="certain")  # not in the queue
    _candidates(engine, nine, (b, "0.7"), (c, "0.6"), (d, "0.5"))
    resp = client.get("/v1/admin/matches/uncertain", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert [item["alias"]["id"] for item in body["items"]] == [str(nine), str(five), str(one)]
    first = body["items"][0]
    assert first["alias"]["chain_name"] == "רשת בדויה"
    assert first["alias"]["alias_text"] == "כינוי תשע"
    assert first["alias"]["product_id"] == str(b)
    assert first["alias"]["product_name"] == "מוצר ב"
    assert first["alias"]["confidence"] == 0.6
    assert first["alias"]["occurrences"] == 9
    assert [(x["product_id"], x["score"]) for x in first["candidates"]] == [
        (str(b), 0.7),
        (str(c), 0.6),
        (str(d), 0.5),
    ]
    assert first["candidates"][1]["product_name"] == "מוצר ג"
    assert body["items"][1]["candidates"] == []


def test_uncertain_ties_by_oldest_update(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    a = _product(factory)
    newer = _alias(engine, chain, a, occurrences=2, updated_at=LATER)
    older = _alias(engine, chain, a, occurrences=2, updated_at=NOW)
    body = client.get("/v1/admin/matches/uncertain", headers=_auth()).json()
    assert [i["alias"]["id"] for i in body["items"]] == [str(older), str(newer)]


def test_pages(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    a = _product(factory)
    ids = [_alias(engine, chain, a, occurrences=n) for n in (3, 2, 1)]
    body = client.get(
        "/v1/admin/matches/uncertain", params={"limit": 1, "offset": 1}, headers=_auth()
    ).json()
    assert body["total"] == 3
    assert [i["alias"]["id"] for i in body["items"]] == [str(ids[1])]
    for params in ({"limit": 201}, {"limit": 0}, {"offset": -1}):
        resp = client.get("/v1/admin/matches/uncertain", params=params, headers=_auth())
        assert resp.status_code == 422
    assert (
        client.get(
            "/v1/admin/matches/uncertain", params={"limit": 200}, headers=_auth()
        ).status_code
        == 200
    )


def test_disputed_with_vote_counts(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    a, b = _product(factory, "מוצר א"), _product(factory, "מוצר ב")
    alias = _alias(engine, chain, a, text_="כינוי במחלוקת")
    u1, u2, u3 = (_user(engine) for _ in range(3))
    with factory() as session:
        matching_service.record_vote(session, alias, u1, "confirm", now=NOW)
        matching_service.record_vote(session, alias, u2, "other", b, now=NOW)
        outcome = matching_service.record_vote(session, alias, u3, "other", b, now=NOW)
        session.commit()
    assert (outcome.state, outcome.product_id) == ("disputed", b)
    _alias(engine, chain, a)  # uncertain: not listed
    body = client.get("/v1/admin/matches/disputed", headers=_auth()).json()
    assert body["total"] == 1
    [item] = body["items"]
    assert item["alias"]["id"] == str(alias)
    assert item["alias"]["product_id"] == str(b)
    assert item["alias"]["alias_text"] == "כינוי במחלוקת"
    assert [(v["product_id"], v["product_name"], v["votes"]) for v in item["votes"]] == [
        (str(b), "מוצר ב", 2),
        (str(a), "מוצר א", 1),
    ]


def test_proposed_products_with_alias_count(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    proposed = _proposed(factory, "מוצר מוצע", barcode="7000000000017")
    lonely = _proposed(factory, "מוצר מוצע בודד")
    _product(factory)  # active: not listed
    _alias(engine, chain, proposed)
    _alias(engine, chain, proposed)
    body = client.get("/v1/admin/products/proposed", headers=_auth()).json()
    assert body["total"] == 2
    found = {i["id"]: i for i in body["items"]}
    assert found[str(proposed)]["alias_count"] == 2
    assert found[str(proposed)]["name"] == "מוצר מוצע"
    assert found[str(proposed)]["barcode"] == "7000000000017"
    assert found[str(lonely)]["alias_count"] == 0


# --- approving a match ---


def test_approve_uncertain_match(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    a = _product(factory)
    alias = _alias(engine, chain, a)
    resp = client.post(f"/v1/admin/matches/{alias}/approve", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "alias_id": str(alias),
        "state": "final",
        "product_id": str(a),
        "changed": True,
        "realigned_alias_ids": [],
    }
    row = _alias_row(engine, alias)
    assert (row["state"], row["product_id"], row["confidence"]) == ("final", a, Decimal(1))
    vote = _one(engine, "SELECT * FROM match_votes WHERE alias_id = :a", a=alias)
    assert (vote["role"], vote["user_id"], vote["vote"]) == ("operator", operator, "confirm")


def test_approve_with_another_product(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    a, b = _product(factory), _product(factory)
    alias = _alias(engine, chain, a)
    resp = client.post(
        f"/v1/admin/matches/{alias}/approve", headers=_auth(), json={"product_id": str(b)}
    )
    assert resp.status_code == 200
    assert (resp.json()["state"], resp.json()["product_id"]) == ("final", str(b))


def test_approve_realigns_final_copies(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    a, b = _product(factory), _product(factory)
    first = _alias(engine, chain, a, "final", "עגבניות שרי", barcode="7000000000024")
    copy = _alias(engine, chain, a, "final", "עגבניות שרי", barcode=None)
    other_text = _alias(engine, chain, a, "final", "מלפפון")
    other_chain_id, _ = _store(factory, chain_code="7290000000777", code="202")
    other_chain = _alias(engine, other_chain_id, a, "final", "עגבניות שרי")
    resp = client.post(
        f"/v1/admin/matches/{first}/approve", headers=_auth(), json={"product_id": str(b)}
    )
    assert resp.status_code == 200
    assert resp.json()["realigned_alias_ids"] == [str(copy)]
    for alias_id in (first, copy):
        row = _alias_row(engine, alias_id)
        assert (row["state"], row["product_id"], row["confidence"]) == ("final", b, Decimal(1))
    assert _alias_row(engine, other_text)["product_id"] == a
    assert _alias_row(engine, other_chain)["product_id"] == a


def test_approve_errors(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    a = _product(factory)
    resp = client.post(f"/v1/admin/matches/{uuid.uuid4()}/approve", headers=_auth())
    assert (resp.status_code, resp.json()["error"]["code"]) == (404, "alias_not_found")
    alias = _alias(engine, chain, a)
    resp = client.post(
        f"/v1/admin/matches/{alias}/approve",
        headers=_auth(),
        json={"product_id": str(uuid.uuid4())},
    )
    assert (resp.status_code, resp.json()["error"]["code"]) == (422, "invalid_vote")
    assert _alias_row(engine, alias)["state"] == "uncertain"
    assert _rows(engine, "SELECT * FROM match_votes") == []


# --- approving a product ---


def test_approve_product(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], operator: uuid.UUID
) -> None:
    proposed = _proposed(factory, "מוצר מוצע")
    resp = client.post(f"/v1/admin/products/{proposed}/approve", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == {"product_id": str(proposed), "status": "active", "changed": True}
    assert _product_row(engine, proposed)["status"] == "active"
    again = client.post(f"/v1/admin/products/{proposed}/approve", headers=_auth())
    assert again.status_code == 200
    assert again.json()["changed"] is False
    missing = client.post(f"/v1/admin/products/{uuid.uuid4()}/approve", headers=_auth())
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "product_not_found")


def test_approve_merged_product_is_409(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], operator: uuid.UUID
) -> None:
    keep, remove = _product(factory), _proposed(factory, "כפול")
    assert (
        client.post(
            "/v1/admin/products/merge",
            headers=_auth(),
            json={"keep_id": str(keep), "remove_id": str(remove)},
        ).status_code
        == 200
    )
    resp = client.post(f"/v1/admin/products/{remove}/approve", headers=_auth())
    assert (resp.status_code, resp.json()["error"]["code"]) == (409, "product_merged")
    assert _product_row(engine, remove)["status"] == "merged_into"


# --- merging ---

R_BARCODE = "7000000000031"
K_BARCODE = "7000000000048"


def test_merge(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], operator: uuid.UUID
) -> None:
    chain_id, store_id = _store(factory)
    keep = _proposed(factory, "חלב בדוי 1 ליטר")  # no barcode
    # remove: from the price file, with its barcode and a certain alias; two observations.
    _prices(factory, chain_id, _price_file(_item(R_BARCODE, "5.90", "חלב בדוי 1ל")), NOW)
    _prices(factory, chain_id, _price_file(_item(R_BARCODE, "6.40", "חלב בדוי 1ל")), LATER)
    _promos(factory, chain_id, _promo_file(_promotion_of(R_BARCODE)), LATER)
    remove = _one(engine, "SELECT id FROM products WHERE barcode = :b", b=R_BARCODE)["id"]
    [alias] = _rows(engine, "SELECT * FROM product_aliases WHERE product_id = :p", p=remove)
    before = _rows(
        engine,
        "SELECT id, unit_price_agorot, observed_at, source, store_id FROM price_observations "
        "ORDER BY id",
    )
    assert len(before) == 2

    resp = client.post(
        "/v1/admin/products/merge",
        headers=_auth(),
        json={"keep_id": str(keep), "remove_id": str(remove)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["remove_status"] == "merged_into"
    assert (body["aliases_moved"], body["observations_moved"]) == (1, 2)
    assert (body["promotion_products_moved"], body["barcode_moved"]) == (1, True)

    moved = _alias_row(engine, alias["id"])
    assert (moved["product_id"], moved["state"]) == (keep, alias["state"])
    after = _rows(
        engine,
        "SELECT id, unit_price_agorot, observed_at, source, store_id, product_id "
        "FROM price_observations ORDER BY id",
    )
    assert [{k: v for k, v in r.items() if k != "product_id"} for r in after] == before
    assert {r["product_id"] for r in after} == {keep}
    assert _rows(engine, "SELECT product_id FROM promotion_products") == [{"product_id": keep}]
    assert _product_row(engine, keep)["barcode"] == R_BARCODE
    gone = _product_row(engine, remove)
    assert (gone["status"], gone["merged_into_id"], gone["barcode"]) == ("merged_into", keep, None)
    current = _rows(engine, "SELECT product_id, unit_price_agorot, store_id FROM current_prices")
    assert current == [{"product_id": keep, "unit_price_agorot": 640, "store_id": store_id}]


def _promotion_of(barcode: str) -> str:
    return _promotion("9001", _promo_item(barcode, reward="1", price="5.00"))


def test_merge_moves_votes_candidates_and_shared_promotions(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], operator: uuid.UUID
) -> None:
    chain_id, _ = _store(factory)
    _prices(
        factory,
        chain_id,
        _price_file(_item(K_BARCODE, "3.00", "גבינה"), _item(R_BARCODE, "3.10", "גבינה כפולה")),
    )
    _promos(
        factory,
        chain_id,
        _promo_file(
            _promotion(
                "9002",
                _promo_item(K_BARCODE, reward="1", price="2.00"),
                _promo_item(R_BARCODE, reward="1", price="2.00"),
            )
        ),
    )
    keep = _one(engine, "SELECT id FROM products WHERE barcode = :b", b=K_BARCODE)["id"]
    remove = _one(engine, "SELECT id FROM products WHERE barcode = :b", b=R_BARCODE)["id"]
    other = _product(factory)
    uncertain = _alias(engine, chain_id, other, occurrences=4)
    _candidates(engine, uncertain, (other, "0.7"), (remove, "0.6"), (keep, "0.5"))
    voter = _user(engine)
    with factory() as session:
        matching_service.record_vote(session, uncertain, voter, "other", remove, now=NOW)
        session.commit()

    resp = client.post(
        "/v1/admin/products/merge",
        headers=_auth(),
        json={"keep_id": str(keep), "remove_id": str(remove)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body["votes_moved"], body["candidates_removed"]) == (1, 1)
    assert body["barcode_moved"] is False  # keep has its own: remove keeps its barcode
    assert _product_row(engine, remove)["barcode"] == R_BARCODE
    assert _rows(engine, "SELECT product_id FROM promotion_products") == [{"product_id": keep}]
    vote = _one(engine, "SELECT * FROM match_votes")
    assert vote["product_id"] == keep
    assert [
        r["product_id"]
        for r in _rows(engine, "SELECT product_id FROM match_candidates ORDER BY rank")
    ] == [other, keep]
    assert _alias_row(engine, uncertain)["occurrences"] == 4


def test_merge_keeps_alias_occurrences(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    # An alias's key (chain, alias_norm, barcode) does not include its product: two aliases of
    # one key cannot exist, so a merge never collides. Each moves with its occurrences.
    keep, remove = _product(factory), _product(factory)
    mine = _alias(engine, chain, keep, text_="שוקולד", barcode=None, occurrences=2)
    theirs = _alias(engine, chain, remove, text_="שוקולד", barcode="7000000000055", occurrences=3)
    resp = client.post(
        "/v1/admin/products/merge",
        headers=_auth(),
        json={"keep_id": str(keep), "remove_id": str(remove)},
    )
    assert resp.status_code == 200
    assert (_alias_row(engine, mine)["product_id"], _alias_row(engine, mine)["occurrences"]) == (
        keep,
        2,
    )
    assert (
        _alias_row(engine, theirs)["product_id"],
        _alias_row(engine, theirs)["occurrences"],
    ) == (keep, 3)


def test_merge_errors_change_nothing(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    keep, remove, third = _product(factory), _product(factory), _product(factory)
    alias = _alias(engine, chain, remove)

    def merge(k: uuid.UUID, r: uuid.UUID) -> Any:
        return client.post(
            "/v1/admin/products/merge",
            headers=_auth(),
            json={"keep_id": str(k), "remove_id": str(r)},
        )

    resp = merge(keep, keep)
    assert (resp.status_code, resp.json()["error"]["code"]) == (422, "invalid_merge")
    resp = merge(keep, uuid.uuid4())
    assert (resp.status_code, resp.json()["error"]["code"]) == (404, "product_not_found")
    assert merge(third, remove).status_code == 200
    resp = merge(keep, remove)
    assert (resp.status_code, resp.json()["error"]["code"]) == (409, "product_merged")
    resp = merge(remove, keep)
    assert (resp.status_code, resp.json()["error"]["code"]) == (409, "product_merged")
    assert _alias_row(engine, alias)["product_id"] == third
    assert _product_row(engine, keep)["status"] == "active"


def test_merge_into_a_merged_chain_follows_one_hop(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], operator: uuid.UUID
) -> None:
    a, b, c = _product(factory), _product(factory), _product(factory)
    for keep, remove in ((b, a), (c, b)):
        assert (
            client.post(
                "/v1/admin/products/merge",
                headers=_auth(),
                json={"keep_id": str(keep), "remove_id": str(remove)},
            ).status_code
            == 200
        )
    assert _product_row(engine, a)["merged_into_id"] == c
    assert _product_row(engine, b)["merged_into_id"] == c


def test_ingestion_after_merge_writes_to_keep(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], operator: uuid.UUID
) -> None:
    chain_id, _ = _store(factory)
    _prices(
        factory,
        chain_id,
        _price_file(_item(K_BARCODE, "3.00", "גבינה"), _item(R_BARCODE, "3.10", "גבינה כפולה")),
    )
    keep = _one(engine, "SELECT id FROM products WHERE barcode = :b", b=K_BARCODE)["id"]
    remove = _one(engine, "SELECT id FROM products WHERE barcode = :b", b=R_BARCODE)["id"]
    assert (
        client.post(
            "/v1/admin/products/merge",
            headers=_auth(),
            json={"keep_id": str(keep), "remove_id": str(remove)},
        ).status_code
        == 200
    )
    assert _product_row(engine, remove)["barcode"] == R_BARCODE
    _prices(factory, chain_id, _price_file(_item(R_BARCODE, "2.50", "גבינה כפולה")), LATER)
    latest = _rows(
        engine, "SELECT product_id, unit_price_agorot FROM price_observations ORDER BY id"
    )[-1]
    assert latest == {"product_id": keep, "unit_price_agorot": 250}
    assert {r["product_id"] for r in _rows(engine, "SELECT product_id FROM product_aliases")} == {
        keep
    }


# --- occurrences ---


def test_match_twice_counts_two(factory: sessionmaker[Session], chain: uuid.UUID) -> None:
    _product(factory, "קוטג בדוי 5%")
    with factory() as session:
        first = matching_service.match(session, "קוטג בדוי 5%", chain, now=NOW)
        second = matching_service.match(session, "קוטג בדוי 5%", chain, now=NOW)
        session.commit()
    assert first.alias_id == second.alias_id is not None
    with factory() as session:
        occurrences = session.execute(
            text("SELECT occurrences FROM product_aliases WHERE id = :id"), {"id": first.alias_id}
        ).scalar_one()
    assert occurrences == 2


def test_unmatched_counts_nothing(factory: sessionmaker[Session], chain: uuid.UUID) -> None:
    with factory() as session:
        assert matching_service.match(session, "***", chain, now=NOW).alias_id is None
        session.commit()


def test_file_items_count_once_per_call(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a = _product(factory, "עגבניות שרי")
    known = _alias(engine, chain, a, text_="עגבניות שרי", occurrences=1)
    items = [FileItem("עגבניות שרי"), FileItem("עגבניות שרי"), FileItem("מלפפון בדוי")]
    with factory() as session:
        result = matching_service.match_file_items(session, chain, items, now=NOW)
        session.commit()
    assert result[0] == result[1] == a
    assert _alias_row(engine, known)["occurrences"] == 2
    [new] = _rows(engine, "SELECT occurrences FROM product_aliases WHERE id <> :k", k=known)
    assert new["occurrences"] == 1


# --- the audit log ---


def test_admin_actions_are_logged(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.admin")
    a = _product(factory)
    alias = _alias(engine, chain, a, text_="טקסט סודי של כינוי")
    client.post(f"/v1/admin/matches/{alias}/approve", headers=_auth())
    [record] = [r for r in caplog.records if r.getMessage() == "admin_action"]
    assert record.__dict__["action"] == "approve_match"
    assert record.__dict__["operator_user_id"] == str(operator)
    assert record.__dict__["alias_id"] == str(alias)
    assert "טקסט סודי" not in repr(record.__dict__)


# --- the CLI ---


def _cli(factory: sessionmaker[Session], *argv: str) -> int:
    return cli.run(list(argv), factory, SETTINGS)


def test_cli_uncertain(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = _product(factory)
    low = _alias(engine, chain, a, occurrences=1, text_="כינוי\tעם טאב")
    high = _alias(engine, chain, a, occurrences=7)
    assert _cli(factory, "uncertain", "--operator", OPERATOR_UID) == 0
    out, err = capsys.readouterr()
    lines = out.splitlines()
    assert [line.split("\t")[0] for line in lines] == [str(high), str(low)]
    assert lines[1].split("\t")[3] == "כינוי עם טאב"
    assert "2 of 2" in err


def test_cli_refuses_a_uid_not_in_the_list(
    engine: Engine, factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    _user(engine, UNLISTED_UID)
    assert _cli(factory, "uncertain", "--operator", UNLISTED_UID) == 1
    assert "not an operator" in capsys.readouterr().err
    # Listed, but no registered user.
    assert _cli(factory, "proposed", "--operator", OPERATOR_UID) == 1


def test_cli_actions(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, b = _product(factory), _product(factory)
    proposed = _proposed(factory, "מוצר מוצע")
    alias = _alias(engine, chain, a)
    assert _cli(factory, "approve", str(alias), str(b), "--operator", OPERATOR_UID) == 0
    assert (_alias_row(engine, alias)["state"], _alias_row(engine, alias)["product_id"]) == (
        "final",
        b,
    )
    assert _cli(factory, "approve-product", str(proposed), "--operator", OPERATOR_UID) == 0
    assert _product_row(engine, proposed)["status"] == "active"
    assert _cli(factory, "merge", str(b), str(a), "--operator", OPERATOR_UID) == 0
    assert _product_row(engine, a)["merged_into_id"] == b
    capsys.readouterr()
    assert _cli(factory, "merge", str(b), str(b), "--operator", OPERATOR_UID) == 1
    assert "invalid_merge" in capsys.readouterr().err
    assert _cli(factory, "approve", "not-a-uuid", "--operator", OPERATOR_UID) == 2
    assert _cli(factory, "approve", str(alias)) == 2  # no --operator


def test_cli_refuses_without_database(capsys: pytest.CaptureFixture[str], monkeypatch: Any) -> None:
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(DATABASE_URL="postgresql+psycopg://nobody:wrong@127.0.0.1:1/none"),
    )
    assert cli.main(["uncertain", "--operator", OPERATOR_UID]) == 1
    assert "no database" in capsys.readouterr().err


# --- the migration ---


def test_models_match_migrations(admin_url: str) -> None:
    command.check(alembic_config(admin_url))  # raises when autogenerate would find a change


def test_migration_roundtrip(db_url: str) -> None:
    url = create_database(db_url, "cw_admin_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    try:
        command.upgrade(cfg, "0013")
        command.upgrade(cfg, "0014")
        with eng.connect() as conn:
            columns = {
                (r[0], r[1])
                for r in conn.execute(
                    text(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE column_name IN ('occurrences', 'merged_into_id')"
                    )
                )
            }
        assert columns == {("product_aliases", "occurrences"), ("products", "merged_into_id")}
        command.downgrade(cfg, "0013")
        command.upgrade(cfg, "head")
    finally:
        eng.dispose()


# --- review follow-ups ---


class RejectingVerifier(FakeVerifier):
    """Every Firebase token is forged (bad signature, audience, expiry...)."""

    def verify(self, id_token: str) -> str:
        raise invalid_token()


def test_forged_operator_token_is_401_and_changes_nothing(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID, operator: uuid.UUID
) -> None:
    client = _client(engine, factory, RejectingVerifier)
    a, b = _product(factory), _proposed(factory, "מוצר מוצע")
    alias = _alias(engine, chain, a)
    calls = [
        ("GET", "/v1/admin/matches/disputed", None),
        ("GET", "/v1/admin/matches/uncertain", None),
        ("GET", "/v1/admin/products/proposed", None),
        ("POST", f"/v1/admin/matches/{alias}/approve", None),
        ("POST", f"/v1/admin/products/{b}/approve", None),
        ("POST", "/v1/admin/products/merge", {"keep_id": str(a), "remove_id": str(b)}),
    ]
    before = (_alias_row(engine, alias), _product_row(engine, a), _product_row(engine, b))
    for method, path, body in calls:
        resp = client.request(method, path, headers=_auth(), json=body)
        assert resp.status_code == 401, path
        assert resp.json()["error"]["code"] == "invalid_token"
    assert (_alias_row(engine, alias), _product_row(engine, a), _product_row(engine, b)) == before
    assert _rows(engine, "SELECT * FROM match_votes") == []


@pytest.mark.parametrize("token", ["garbage", "a.b.c"])
def test_malformed_token_is_401(client: TestClient, operator: uuid.UUID, token: str) -> None:
    resp = client.get("/v1/admin/matches/uncertain", headers={"Authorization": f"Bearer {token}"})
    assert (resp.status_code, resp.json()["error"]["code"]) == (401, "invalid_token")


def test_disputed_and_proposed_oldest_first_with_pages(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    a = _product(factory)
    newer = _alias(engine, chain, a, state="disputed", confidence=None, updated_at=LATER)
    older = _alias(engine, chain, a, state="disputed", confidence=None, updated_at=NOW)
    body = client.get("/v1/admin/matches/disputed", headers=_auth()).json()
    assert [i["alias"]["id"] for i in body["items"]] == [str(older), str(newer)]
    page = client.get(
        "/v1/admin/matches/disputed", params={"limit": 1, "offset": 1}, headers=_auth()
    ).json()
    assert (page["total"], [i["alias"]["id"] for i in page["items"]]) == (2, [str(newer)])
    late = _proposed(factory, "מוצר מאוחר", now=LATER)
    early = _proposed(factory, "מוצר מוקדם", now=NOW)
    body = client.get("/v1/admin/products/proposed", headers=_auth()).json()
    assert [i["id"] for i in body["items"]] == [str(early), str(late)]


def test_approve_with_a_merged_product_is_422(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    a, keep, merged = _product(factory), _product(factory), _product(factory)
    with factory() as session:
        matching_service.merge_products(session, keep, merged, operator, now=NOW)
        session.commit()
    alias = _alias(engine, chain, a)
    resp = client.post(
        f"/v1/admin/matches/{alias}/approve", headers=_auth(), json={"product_id": str(merged)}
    )
    assert (resp.status_code, resp.json()["error"]["code"]) == (422, "invalid_vote")
    assert _alias_row(engine, alias)["state"] == "uncertain"


def test_merge_settles_a_disputed_alias_split_between_the_two(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    a, b = _product(factory, "מוצר א"), _product(factory, "מוצר ב")
    alias = _alias(engine, chain, a)
    u1, u2, u3 = (_user(engine) for _ in range(3))
    with factory() as session:
        matching_service.record_vote(session, alias, u1, "confirm", now=NOW)
        matching_service.record_vote(session, alias, u2, "other", b, now=NOW)
        matching_service.record_vote(session, alias, u3, "other", b, now=NOW)
        session.commit()
    assert _alias_row(engine, alias)["state"] == "disputed"
    resp = client.post(
        "/v1/admin/products/merge",
        headers=_auth(),
        json={"keep_id": str(a), "remove_id": str(b)},
    )
    assert resp.status_code == 200
    row = _alias_row(engine, alias)
    assert (row["state"], row["product_id"], row["confidence"]) == ("final", a, Decimal(1))
    votes = _rows(engine, "SELECT vote, product_id FROM match_votes WHERE alias_id = :a", a=alias)
    assert votes == [{"vote": "confirm", "product_id": None}] * 3


def test_merging_an_active_product_into_a_proposed_one_approves_it(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], operator: uuid.UUID
) -> None:
    keep, remove = _proposed(factory, "מוצר מוצע"), _product(factory)
    resp = client.post(
        "/v1/admin/products/merge",
        headers=_auth(),
        json={"keep_id": str(keep), "remove_id": str(remove)},
    )
    assert resp.status_code == 200
    assert _product_row(engine, keep)["status"] == "active"
    # A proposed one merged into a proposed one leaves it proposed.
    other, extra = _proposed(factory, "עוד מוצר מוצע"), _proposed(factory, "כפול מוצע")
    with factory() as session:
        matching_service.merge_products(session, other, extra, operator, now=NOW)
        session.commit()
    assert _product_row(engine, other)["status"] == "proposed"


def test_proposing_a_merged_barcode_gives_the_product_kept(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], operator: uuid.UUID
) -> None:
    chain_id, _ = _store(factory)
    _prices(
        factory,
        chain_id,
        _price_file(_item(K_BARCODE, "3.00", "גבינה"), _item(R_BARCODE, "3.10", "גבינה כפולה")),
    )
    keep = _one(engine, "SELECT id FROM products WHERE barcode = :b", b=K_BARCODE)["id"]
    remove = _one(engine, "SELECT id FROM products WHERE barcode = :b", b=R_BARCODE)["id"]
    with factory() as session:
        matching_service.merge_products(session, keep, remove, operator, now=NOW)
        session.commit()
    assert _proposed(factory, "גבינה כפולה", barcode=R_BARCODE) == keep


def test_merge_puts_keep_in_place_of_remove_among_candidates(
    client: TestClient,
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
) -> None:
    other, remove, keep = _product(factory), _product(factory), _product(factory)
    alias = _alias(engine, chain, other)
    _candidates(engine, alias, (remove, "0.7"), (other, "0.6"))
    with factory() as session:
        outcome = matching_service.merge_products(session, keep, remove, operator, now=NOW)
        session.commit()
    assert outcome.candidates_removed == 1
    rows = _rows(engine, "SELECT rank, product_id, score FROM match_candidates ORDER BY rank")
    assert rows == [
        {"rank": 1, "product_id": keep, "score": Decimal("0.700")},
        {"rank": 2, "product_id": other, "score": Decimal("0.600")},
    ]


def test_cli_disputed_and_proposed(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    operator: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, b = _product(factory), _product(factory)
    alias = _alias(engine, chain, a)
    u1, u2, u3 = (_user(engine) for _ in range(3))
    with factory() as session:
        matching_service.record_vote(session, alias, u1, "confirm", now=NOW)
        matching_service.record_vote(session, alias, u2, "other", b, now=NOW)
        matching_service.record_vote(session, alias, u3, "other", b, now=NOW)
        session.commit()
    capsys.readouterr()
    assert _cli(factory, "disputed", "--operator", OPERATOR_UID) == 0
    [line] = capsys.readouterr().out.splitlines()
    cells = line.split("\t")
    assert cells[0] == str(alias)
    assert cells[-1] == f"{b}:2, {a}:1"
    proposed = _proposed(factory, "מוצר מוצע")
    _alias(engine, chain, proposed)
    assert _cli(factory, "proposed", "--operator", OPERATOR_UID) == 0
    [line] = capsys.readouterr().out.splitlines()
    assert line.split("\t")[:2] == [str(proposed), "1"]


def test_cli_database_error(
    engine: Engine,
    factory: sessionmaker[Session],
    operator: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: Any,
) -> None:
    def broken(*_a: Any, **_k: Any) -> Any:
        raise OperationalError("SELECT", {}, Exception("gone"))

    monkeypatch.setattr(matching_service, "uncertain_matches", broken)
    assert _cli(factory, "uncertain", "--operator", OPERATOR_UID) == 1
    err = capsys.readouterr().err
    assert "database error (OperationalError)" in err
    assert "Traceback" not in err
