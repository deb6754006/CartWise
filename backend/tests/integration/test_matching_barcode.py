"""Barcode matching (Story 4.1), against Postgres. Every product and barcode here is invented."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import make_engine
from app.modules.catalog import service as catalog_service
from app.modules.catalog.service import ProductRecord
from app.modules.matching import service as matching_service
from app.modules.matching.service import UNMATCHED, MatchContext, MatchResult
from tests.integration.pg import alembic_config, create_database
from tests.integration.test_prices import _item, _price_file, _prices, _store

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
MILK = "7290000000001"
OTHER = "7290000000019"
UNKNOWN = "7290000000026"
CONTEXT = MatchContext("receipt", 1390)


@pytest.fixture(scope="module")
def matching_url(db_url: str) -> str:
    """A database of its own: these tests truncate and count rows."""
    url = create_database(db_url, "cw_matching")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(matching_url: str) -> Iterator[Engine]:
    eng = make_engine(matching_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE match_candidates, product_aliases, promotion_products, promotions, "
                "price_observations, products, ingestion_alerts, "
                "ingestion_files, ingestion_runs, stores, user_clubs, clubs, chains"
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _chain(factory: sessionmaker[Session], code: str = "7290000000000") -> uuid.UUID:
    with factory() as session:
        chain_id = catalog_service.ensure_chain(session, code, "רשת בדויה")
        session.commit()
    return chain_id


@pytest.fixture
def chain(factory: sessionmaker[Session]) -> uuid.UUID:
    return _chain(factory)


def _product(factory: sessionmaker[Session], barcode: str, name: str = "מוצר בדוי") -> uuid.UUID:
    with factory() as session:
        ids = catalog_service.ensure_products_by_barcode(
            session, [ProductRecord(barcode, name, None, None, False)], now=NOW
        )
        session.commit()
    return ids[barcode]


def _match(
    factory: sessionmaker[Session],
    alias: str,
    chain_id: uuid.UUID,
    barcode: str | None,
    now: datetime = NOW,
) -> MatchResult:
    with factory() as session:
        result = matching_service.match(session, alias, chain_id, barcode, CONTEXT, now=now)
        session.commit()
    return result


def _aliases(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM product_aliases ORDER BY id"))
        return [dict(row._mapping) for row in rows]


def _set_state(engine: Engine, alias_id: uuid.UUID, state: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE product_aliases SET state = :s WHERE id = :id"),
            {"s": state, "id": alias_id},
        )


# --- match ---


def test_a_barcode_with_a_product(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    product_id = _product(factory, MILK)
    result = _match(factory, "  חלב 3%   1ל ", chain, MILK)
    assert (result.state, result.product_id, result.confidence) == ("certain", product_id, 1.0)
    assert result.candidates == ()
    [alias] = _aliases(engine)
    assert alias["id"] == result.alias_id
    assert alias["chain_id"] == chain
    assert alias["alias_text"] == "חלב 3% 1ל"
    assert alias["alias_norm"] == catalog_service.normalize_he("חלב 3% 1ל")
    assert alias["barcode"] == MILK
    assert alias["product_id"] == product_id
    assert (alias["state"], alias["confidence"]) == ("certain", Decimal("1.000"))
    assert alias["created_at"] == alias["updated_at"] == NOW


def test_the_same_alias_again(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    _product(factory, MILK)
    first = _match(factory, "חלב 3% 1ל", chain, MILK)
    again = _match(factory, "חלב  3%  1ל", chain, MILK, NOW + timedelta(hours=1))
    assert again == first
    [alias] = _aliases(engine)
    assert alias["updated_at"] == NOW  # nothing changed, nothing written


def test_another_text_of_the_same_barcode(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    product_id = _product(factory, MILK)
    first = _match(factory, "חלב 3% 1ל", chain, MILK)
    second = _match(factory, "חלב תנובה 3%", chain, MILK)
    assert second.alias_id != first.alias_id
    assert second.product_id == first.product_id == product_id
    assert len(_aliases(engine)) == 2


def test_another_chain(engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID) -> None:
    product_id = _product(factory, MILK)
    other_chain = _chain(factory, "7290000000099")
    first = _match(factory, "חלב 3% 1ל", chain, MILK)
    second = _match(factory, "חלב 3% 1ל", other_chain, MILK)
    assert second.alias_id != first.alias_id
    assert second.product_id == product_id
    assert {a["chain_id"] for a in _aliases(engine)} == {chain, other_chain}


def test_a_barcode_with_no_product(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    # Matched by text since Story 4.2 (see test_matching_text.py): no product gets the barcode.
    _product(factory, MILK)
    result = _match(factory, "מוצר לא מוכר", chain, UNKNOWN)
    assert result.state != "unmatched"
    [alias] = _aliases(engine)
    assert (alias["id"], alias["barcode"]) == (result.alias_id, UNKNOWN)
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM products WHERE barcode = :b"), {"b": UNKNOWN}
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize("barcode", ["123", "00000000", "abc", "", None])
def test_no_valid_barcode(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID, barcode: str | None
) -> None:
    # Matched by text since Story 4.2: the alias is saved with no barcode.
    _product(factory, MILK)
    result = _match(factory, "חלב 3% 1ל", chain, barcode)
    assert result.state != "unmatched"
    [alias] = _aliases(engine)
    assert (alias["id"], alias["barcode"]) == (result.alias_id, None)


def test_an_empty_text(engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID) -> None:
    _product(factory, MILK)
    assert _match(factory, "   ", chain, MILK) == UNMATCHED
    assert _aliases(engine) == []


@pytest.mark.parametrize("state", ["final", "disputed"])
def test_a_settled_alias_is_not_changed(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID, state: str
) -> None:
    a = _product(factory, MILK)
    b = _product(factory, OTHER)
    first = _match(factory, "חלב 3% 1ל", chain, MILK)
    assert first.alias_id is not None
    with engine.begin() as conn:
        # The barcode now belongs to another product (as after a merge, Story 4.5).
        conn.execute(text("UPDATE products SET barcode = NULL WHERE id = :a"), {"a": a})
        conn.execute(text("UPDATE products SET barcode = :m WHERE id = :b"), {"m": MILK, "b": b})
    _set_state(engine, first.alias_id, state)
    before = _aliases(engine)

    result = _match(factory, "חלב 3% 1ל", chain, MILK, NOW + timedelta(hours=1))
    assert (result.state, result.product_id, result.alias_id) == (state, a, first.alias_id)
    assert _aliases(engine) == before


def test_a_certain_alias_follows_the_barcode(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a = _product(factory, MILK)
    b = _product(factory, OTHER)
    first = _match(factory, "חלב 3% 1ל", chain, MILK)
    with engine.begin() as conn:
        conn.execute(text("UPDATE products SET barcode = NULL WHERE id = :a"), {"a": a})
        conn.execute(text("UPDATE products SET barcode = :m WHERE id = :b"), {"m": MILK, "b": b})

    later = NOW + timedelta(hours=1)
    result = _match(factory, "חלב 3% 1ל", chain, MILK, later)
    assert (result.state, result.product_id, result.alias_id) == ("certain", b, first.alias_id)
    [alias] = _aliases(engine)
    assert (alias["product_id"], alias["state"], alias["updated_at"]) == (b, "certain", later)


def test_an_uncertain_alias_becomes_certain(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    product_id = _product(factory, MILK)
    first = _match(factory, "חלב 3% 1ל", chain, MILK)
    assert first.alias_id is not None
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE product_aliases SET state = 'uncertain', confidence = 0.5, "
                "product_id = NULL WHERE id = :id"
            ),
            {"id": first.alias_id},
        )
    result = _match(factory, "חלב 3% 1ל", chain, MILK)
    assert (result.state, result.product_id, result.confidence) == ("certain", product_id, 1.0)


def test_a_lower_confidence_becomes_one(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    product_id = _product(factory, MILK)
    first = _match(factory, "חלב 3% 1ל", chain, MILK)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE product_aliases SET confidence = 0.8 WHERE id = :id"),
            {"id": first.alias_id},
        )
    result = _match(factory, "חלב 3% 1ל", chain, MILK)
    assert (result.state, result.product_id, result.confidence) == ("certain", product_id, 1.0)
    [alias] = _aliases(engine)
    assert alias["confidence"] == Decimal("1.000")


def test_the_match_log(
    factory: sessionmaker[Session], chain: uuid.UUID, caplog: pytest.LogCaptureFixture
) -> None:
    _product(factory, MILK)
    with caplog.at_level("INFO", logger="app.matching"):
        _match(factory, "חלב סודי", chain, MILK)
    [record] = [r for r in caplog.records if r.getMessage() == "matching_match"]
    assert (record.state, record.source, record.had_barcode) == (  # type: ignore[attr-defined]
        "certain",
        "receipt",
        True,
    )
    assert "חלב סודי" not in str(record.__dict__)


# --- match_barcodes and ingestion ---


def test_match_barcodes(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    milk = _product(factory, MILK)
    other = _product(factory, OTHER)
    items = [
        ("חלב 3% 1ל", MILK),
        ("חלב  3% 1ל", MILK),  # the same key: one alias
        ("חלב תנובה", MILK),
        ("מוצר אחר", OTHER),
        ("לא מוכר", UNKNOWN),
        ("בלי ברקוד", None),
        ("ברקוד שגוי", "123"),
        ("   ", OTHER),
    ]
    with factory() as session, caplog.at_level("INFO", logger="app.matching"):
        assert matching_service.match_barcodes(session, chain, items, now=NOW) == 3
        session.commit()
    [record] = [r for r in caplog.records if r.getMessage() == "matching_match_bulk"]
    counts = {k: getattr(record, k) for k in ("items", "invalid_barcode", "no_product")}
    assert counts == {"items": 8, "invalid_barcode": 2, "no_product": 1}
    assert record.aliases_new == 3  # type: ignore[attr-defined]
    assert "לא מוכר" not in str(record.__dict__)
    aliases = _aliases(engine)
    assert sorted((a["alias_text"], a["product_id"]) for a in aliases) == sorted(
        [("חלב 3% 1ל", milk), ("חלב תנובה", milk), ("מוצר אחר", other)]
    )
    assert {(a["state"], a["confidence"]) for a in aliases} == {("certain", Decimal("1.000"))}

    with factory() as session:
        assert matching_service.match_barcodes(session, chain, items, now=NOW) == 0


def test_match_barcodes_follows_the_barcode(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a = _product(factory, MILK)
    b = _product(factory, OTHER)
    names = {"certain": "חלב 1", "uncertain": "חלב 2", "final": "חלב 3"}
    for state, name in names.items():
        alias = _match(factory, name, chain, MILK)
        assert alias.alias_id is not None
        _set_state(engine, alias.alias_id, state)
    before = {x["alias_text"]: x for x in _aliases(engine)}
    with engine.begin() as conn:
        # The barcode now belongs to another product (as after a merge, Story 4.5).
        conn.execute(text("UPDATE products SET barcode = NULL WHERE id = :a"), {"a": a})
        conn.execute(text("UPDATE products SET barcode = :m WHERE id = :b"), {"m": MILK, "b": b})

    later = NOW + timedelta(hours=1)
    with factory() as session:
        items = [(name, MILK) for name in names.values()]
        assert matching_service.match_barcodes(session, chain, items, now=later) == 0
        session.commit()
    after = {x["alias_text"]: x for x in _aliases(engine)}
    for name in (names["certain"], names["uncertain"]):
        assert (after[name]["product_id"], after[name]["state"]) == (b, "certain")
        assert (after[name]["confidence"], after[name]["updated_at"]) == (Decimal("1.000"), later)
        assert after[name]["id"] == before[name]["id"]
    assert after[names["final"]] == before[names["final"]]


def test_match_barcodes_with_the_products_given(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    milk = _product(factory, MILK)
    with factory() as session:
        items = [("חלב", MILK), ("אחר", OTHER)]
        # OTHER has a product, but not in the map given: it is not looked up.
        _product(factory, OTHER)
        new = matching_service.match_barcodes(session, chain, items, product_ids={MILK: milk})
        assert new == 1
        session.commit()
    [alias] = _aliases(engine)
    assert (alias["alias_text"], alias["product_id"]) == ("חלב", milk)


def test_many_aliases(engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID) -> None:
    barcodes = [f"72900{n:08d}" for n in range(2500)]
    with factory() as session:
        catalog_service.ensure_products_by_barcode(
            session, [ProductRecord(b, f"מוצר {b}", None, None, False) for b in barcodes], now=NOW
        )
        items = [(f"מוצר {b}", b) for b in barcodes]
        assert matching_service.match_barcodes(session, chain, items, now=NOW) == 2500
        session.commit()
    assert len(_aliases(engine)) == 2500


def test_a_price_file_saves_aliases(
    engine: Engine, factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    chain_id, _ = _store(factory)
    data = _price_file(
        _item("1000000000001", "13.90", "חלב בדוי"),
        _item("1000000000002", "9.50", "לחם בדוי"),
        _item("1000000000003", "66.00", "גבינה בדויה", weighted="1"),
        _item("7001", "7.90", "עגבניה בדויה", item_type="0"),
    )
    with caplog.at_level("INFO", logger="app.ingestion"):
        _prices(factory, chain_id, data)
    [record] = [r for r in caplog.records if r.getMessage() == "ingestion_prices"]
    assert record.aliases_new == 3  # type: ignore[attr-defined]

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT a.alias_text, a.barcode, a.state, a.chain_id, p.barcode AS product_barcode "
                "FROM product_aliases a JOIN products p ON p.id = a.product_id "
                "WHERE a.barcode IS NOT NULL ORDER BY a.barcode"
            )
        ).all()
    assert [(r.alias_text, r.barcode, r.state, r.chain_id) for r in rows] == [
        ("חלב בדוי", "1000000000001", "certain", chain_id),
        ("לחם בדוי", "1000000000002", "certain", chain_id),
        ("גבינה בדויה", "1000000000003", "certain", chain_id),
    ]
    assert all(r.barcode == r.product_barcode for r in rows)

    caplog.clear()
    with caplog.at_level("INFO", logger="app.ingestion"):
        _prices(factory, chain_id, data, NOW + timedelta(hours=6))
    [record] = [r for r in caplog.records if r.getMessage() == "ingestion_prices"]
    assert record.aliases_new == 0  # type: ignore[attr-defined]
    # The 3 by barcode, and the item with an internal code's, by its name (Story 3.6).
    assert len(_aliases(engine)) == 4


# --- Schema ---


def test_the_schema(engine: Engine) -> None:
    with engine.connect() as conn:
        indexes = dict(conn.execute(text("SELECT indexname, indexdef FROM pg_indexes")).all())
    unique = indexes["uq_product_aliases_chain_id_alias_norm_barcode"]
    assert "NULLS NOT DISTINCT" in unique
    assert "(chain_id, alias_norm, barcode)" in unique
    assert "(product_id)" in indexes["ix_product_aliases_product_id"]


def test_no_barcode_is_one_key(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    insert = text(
        "INSERT INTO product_aliases (id, chain_id, alias_text, alias_norm, state, created_at, "
        "updated_at) VALUES (:id, :c, 'א', 'א', 'uncertain', now(), now())"
    )
    with engine.begin() as conn:
        conn.execute(insert, {"id": uuid.uuid4(), "c": chain})
    with pytest.raises(IntegrityError) as exc, engine.begin() as conn:
        conn.execute(insert, {"id": uuid.uuid4(), "c": chain})
    constraint = exc.value.orig.diag.constraint_name  # type: ignore[union-attr]
    assert constraint == "uq_product_aliases_chain_id_alias_norm_barcode"


def test_the_checks(engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID) -> None:
    insert = text(
        "INSERT INTO product_aliases (id, chain_id, alias_text, alias_norm, state, confidence, "
        "created_at, updated_at) VALUES (:id, :c, 'א', 'א', :state, :confidence, now(), now())"
    )
    for bad, check in (
        ({"state": "maybe", "confidence": 1}, "ck_product_aliases_state"),
        ({"state": "certain", "confidence": 1.5}, "ck_product_aliases_confidence"),
        ({"state": "certain", "confidence": -0.1}, "ck_product_aliases_confidence"),
    ):
        with pytest.raises(IntegrityError) as exc, engine.begin() as conn:
            conn.execute(insert, {"id": uuid.uuid4(), "c": chain, **bad})
        assert exc.value.orig.diag.constraint_name == check  # type: ignore[union-attr]


def test_aliases_migration_roundtrip_adds_no_data(db_url: str) -> None:
    url = create_database(db_url, "cw_aliases_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    try:
        command.upgrade(cfg, "0010")
        assert "product_aliases" not in inspect(eng).get_table_names()
        command.upgrade(cfg, "0011")
        with eng.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM product_aliases")).scalar_one() == 0
        command.downgrade(cfg, "0010")
        tables = set(inspect(eng).get_table_names())
        assert "product_aliases" not in tables
        assert {"products", "chains"} <= tables
    finally:
        eng.dispose()
