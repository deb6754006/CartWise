"""Matching by text (Story 4.2), against Postgres. Every product and barcode here is invented."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import make_engine
from app.modules.catalog import service as catalog_service
from app.modules.catalog.service import ProductRecord
from app.modules.matching import service as matching_service
from app.modules.matching.service import UNMATCHED, MatchContext, MatchResult
from app.modules.pricing import service as pricing_service
from scripts import eval_matching
from tests.integration.pg import alembic_config, create_database
from tests.integration.test_prices import _item, _price_file, _prices, _refresh, _store

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
RECEIPT = MatchContext("receipt")
_codes = iter(range(10**12, 10**13))


@pytest.fixture(scope="module")
def text_url(db_url: str) -> str:
    """A database of its own: these tests truncate and count rows."""
    url = create_database(db_url, "cw_matching_text")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(text_url: str) -> Iterator[Engine]:
    eng = make_engine(text_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE match_votes, match_candidates, product_aliases, promotion_products, "
                "promotions, "
                "price_observations, products, ingestion_alerts, "
                "ingestion_files, ingestion_runs, stores, user_clubs, clubs, chains"
            )
        )
        conn.execute(text("REFRESH MATERIALIZED VIEW current_prices"))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _chain(factory: sessionmaker[Session], code: str = "7290000000000") -> uuid.UUID:
    with factory() as session:
        chain_id = catalog_service.ensure_chain(session, code, "רשת בדויה")
        session.commit()
    return chain_id


@pytest.fixture
def chain(factory: sessionmaker[Session]) -> uuid.UUID:
    return _chain(factory)


def _product(factory: sessionmaker[Session], name: str, barcode: str | None = None) -> uuid.UUID:
    code = barcode or str(next(_codes))
    with factory() as session:
        ids = catalog_service.ensure_products_by_barcode(
            session, [ProductRecord(code, name, None, None, False)], now=NOW
        )
        session.commit()
    return ids[code]


def _match(
    factory: sessionmaker[Session],
    alias: str,
    chain_id: uuid.UUID,
    barcode: str | None = None,
    context: MatchContext | None = RECEIPT,
    now: datetime = NOW,
) -> MatchResult:
    with factory() as session:
        result = matching_service.match(session, alias, chain_id, barcode, context, now=now)
        session.commit()
    return result


def _rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql), params)]


def _aliases(engine: Engine) -> list[dict[str, Any]]:
    return _rows(engine, "SELECT * FROM product_aliases ORDER BY id")


def _candidates(engine: Engine) -> list[dict[str, Any]]:
    return _rows(engine, "SELECT * FROM match_candidates ORDER BY alias_id, rank")


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())  # noqa: S608


# --- the matrix ---


def test_a_certain_match(engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID) -> None:
    product_id = _product(factory, "עגבניות שרי 250 גרם")
    result = _match(factory, "עגבניות שרי 250ג", chain)
    assert (result.state, result.product_id) == ("certain", product_id)
    assert result.confidence is not None and result.confidence >= 0.85
    assert [c.product_id for c in result.candidates] == [product_id]
    [alias] = _aliases(engine)
    assert (alias["id"], alias["state"], alias["product_id"]) == (
        result.alias_id,
        "certain",
        product_id,
    )
    assert alias["barcode"] is None
    assert alias["confidence"] == Decimal(str(result.confidence))
    assert _candidates(engine) == []


def test_two_close_candidates(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    nuts = _product(factory, "שוקולד חלב אגוזים")
    almonds = _product(factory, "שוקולד חלב שקדים")
    result = _match(factory, "שוקולד חלב", chain)
    assert result.state == "uncertain"
    assert {c.product_id for c in result.candidates} == {nuts, almonds}
    first, second = result.candidates
    assert first.score >= second.score
    assert first.score - second.score < 0.1
    [alias] = _aliases(engine)
    assert (alias["state"], alias["product_id"]) == ("uncertain", first.product_id)
    assert alias["confidence"] == Decimal(str(first.score))
    rows = _candidates(engine)
    assert [(r["alias_id"], r["rank"], r["product_id"]) for r in rows] == [
        (result.alias_id, 1, first.product_id),
        (result.alias_id, 2, second.product_id),
    ]
    assert [r["score"] for r in rows] == [Decimal(str(first.score)), Decimal(str(second.score))]


def test_a_middling_score(engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID) -> None:
    coffee = _product(factory, "קפה שחור טחון")
    result = _match(factory, "קפה שחור", chain)
    assert (result.state, result.product_id) == ("uncertain", coffee)
    assert result.confidence is not None and 0.3 <= result.confidence < 0.85
    assert len(_candidates(engine)) == 1


def test_no_candidate_proposes_a_product(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    _product(factory, "חלב 3% 1 ליטר")
    result = _match(factory, "  משחת   שיניים 75 מל ", chain)
    assert result.state == "new_product_proposal"
    assert (result.confidence, result.candidates) == (None, ())
    [proposed] = _rows(engine, "SELECT * FROM products WHERE status = 'proposed'")
    assert proposed["id"] == result.product_id
    assert (proposed["name"], proposed["barcode"]) == ("משחת שיניים 75 מל", None)
    assert proposed["name_norm"] == catalog_service.normalize_he("משחת שיניים 75 מל")
    assert (proposed["pack_size"], proposed["pack_unit"]) == (Decimal(75), "ml")
    [alias] = _aliases(engine)
    assert (alias["id"], alias["state"], alias["product_id"], alias["confidence"]) == (
        result.alias_id,
        "uncertain",
        proposed["id"],
        None,
    )
    assert _candidates(engine) == []


def test_the_same_text_in_another_chain(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    first = _match(factory, "משחת שיניים 75 מל", chain)
    assert first.state == "new_product_proposal"
    other_chain = _chain(factory, "7290000000099")
    second = _match(factory, "משחת שיניים 75 מל", other_chain)
    # A strong candidate, but proposed (nobody approved it): uncertain, and no second proposal.
    assert (second.state, second.product_id) == ("uncertain", first.product_id)
    assert second.candidates[0].product_id == first.product_id
    assert _count(engine, "products") == 1
    # The same chain again: still uncertain on it.
    again = _match(factory, "משחת שיניים 75 מל", chain)
    assert (again.state, again.product_id) == ("uncertain", first.product_id)
    assert _count(engine, "products") == 1


def test_the_size_decides(factory: sessionmaker[Session], chain: uuid.UUID) -> None:
    one = _product(factory, "חלב 1 ליטר")
    two = _product(factory, "חלב 2 ליטר")
    result = _match(factory, "חלב 1ל", chain)
    assert result.product_id == one
    with factory() as session:
        products = catalog_service.product_candidates(session, "חלב 1ל")
    scores = {c.product_id: c.score for c in matching_service.score_candidates("חלב 1ל", products)}
    assert scores[one] > scores[two]


def test_an_unlikely_price(factory: sessionmaker[Session]) -> None:
    chain_id, _ = _store(factory)
    _prices(factory, chain_id, _price_file(_item("1000000000001", "6.00", "חלב 1 ליטר")))
    _refresh(factory)
    with factory() as session:
        [product_id] = catalog_service.product_ids_by_barcode(session, ["1000000000001"]).values()
        assert pricing_service.median_prices(session, [product_id]) == {product_id: 600}
        assert pricing_service.median_prices(session, []) == {}
    sane = _match(factory, "חלב 1ל", chain_id, context=MatchContext("receipt", 600))
    other_chain = _chain(factory, "7290000000099")
    tripled = _match(factory, "חלב 1ל", other_chain, context=MatchContext("receipt", 1800))
    assert sane.product_id == tripled.product_id == product_id
    assert sane.confidence is not None and tripled.confidence is not None
    assert tripled.confidence < sane.confidence


def test_no_context(
    factory: sessionmaker[Session], chain: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    product_id = _product(factory, "חלב 1 ליטר")

    def no_prices(*_args: Any) -> Any:
        raise AssertionError("the price is not used with no context")

    monkeypatch.setattr(pricing_service, "median_prices", no_prices)
    result = _match(factory, "חלב 1ל", chain, context=None)
    # text, size and unit, all 1.
    assert (result.state, result.product_id, result.confidence) == ("certain", product_id, 1.0)


def test_an_unknown_barcode(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    product_id = _product(factory, "עגבניות שרי 250 גרם", "7290000000001")
    caplog.clear()
    with caplog.at_level("INFO", logger="app.matching"):
        result = _match(factory, "עגבניות שרי 250ג", chain, "7290000000026")
    assert (result.state, result.product_id) == ("certain", product_id)
    [alias] = _aliases(engine)
    assert alias["barcode"] == "7290000000026"
    [record] = [r for r in caplog.records if r.getMessage() == "matching_match"]
    assert (record.path, record.had_barcode) == ("text", True)  # type: ignore[attr-defined]


def test_an_invalid_barcode_is_saved_as_none(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    _product(factory, "עגבניות שרי 250 גרם")
    result = _match(factory, "עגבניות שרי 250ג", chain, "123")
    assert result.state == "certain"
    [alias] = _aliases(engine)
    assert alias["barcode"] is None


@pytest.mark.parametrize("state", ["final", "disputed"])
def test_a_settled_alias_is_returned_as_it_is(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
    state: str,
) -> None:
    _product(factory, "שוקולד חלב אגוזים")
    _product(factory, "שוקולד חלב שקדים")
    first = _match(factory, "שוקולד חלב", chain)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE product_aliases SET state = :s WHERE id = :id"),
            {"s": state, "id": first.alias_id},
        )
    before = (_aliases(engine), _candidates(engine), _count(engine, "products"))
    caplog.clear()
    with caplog.at_level("INFO", logger="app.matching"):
        result = _match(factory, "שוקולד  חלב", chain, now=NOW + timedelta(hours=1))
    assert (result.state, result.product_id, result.alias_id) == (
        state,
        first.product_id,
        first.alias_id,
    )
    assert (_aliases(engine), _candidates(engine), _count(engine, "products")) == before
    [record] = [r for r in caplog.records if r.getMessage() == "matching_match"]
    assert record.path == "memory"  # type: ignore[attr-defined]


def test_certain_does_not_go_down(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a = _product(factory, "עגבניות שרי 250 גרם")
    first = _match(factory, "עגבניות שרי 250ג", chain)
    assert (first.state, first.product_id) == ("certain", a)
    # Another product as good: no longer certain by score, and A still leads (ties by id).
    _product(factory, "עגבניות שרי 250 גרם")
    again = _match(factory, "עגבניות שרי 250ג", chain, now=NOW + timedelta(hours=1))
    assert (again.state, again.product_id, again.alias_id) == ("certain", a, first.alias_id)
    [alias] = _aliases(engine)
    assert (alias["state"], alias["product_id"]) == ("certain", a)
    assert _candidates(engine) == []


def test_certain_for_another_product_follows_the_new_state(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a = _product(factory, "קפה שחור טחון")
    first = _match(factory, "קפה שחור", chain)
    with engine.begin() as conn:
        # Certain for another product, as it might have been before.
        b = _product(factory, "תה ירוק")
        conn.execute(
            text("UPDATE product_aliases SET state = 'certain', product_id = :b WHERE id = :id"),
            {"b": b, "id": first.alias_id},
        )
    again = _match(factory, "קפה שחור", chain)
    assert (again.state, again.product_id) == ("uncertain", a)


def test_candidates_are_replaced(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    _product(factory, "שוקולד חלב אגוזים")
    _product(factory, "שוקולד חלב שקדים")
    first = _match(factory, "שוקולד חלב", chain)
    assert len(_candidates(engine)) == 2
    _product(factory, "שוקולד חלב")  # now a certain match
    again = _match(factory, "שוקולד חלב", chain)
    assert (again.state, again.alias_id) == ("certain", first.alias_id)
    assert _candidates(engine) == []


def test_candidates_go_with_their_alias(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    _product(factory, "שוקולד חלב אגוזים")
    _product(factory, "שוקולד חלב שקדים")
    result = _match(factory, "שוקולד חלב", chain)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM product_aliases WHERE id = :id"), {"id": result.alias_id})
    assert _candidates(engine) == []


def test_an_empty_text(engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID) -> None:
    _product(factory, "חלב")
    assert _match(factory, "   ", chain) == UNMATCHED
    assert (_aliases(engine), _count(engine, "products")) == ([], 1)


def test_a_merged_product_is_not_a_candidate(
    factory: sessionmaker[Session], engine: Engine
) -> None:
    merged = _product(factory, "קפה שחור טחון")
    kept = _product(factory, "קפה שחור טחון דק")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE products SET status = 'merged_into' WHERE id = :id"), {"id": merged}
        )
    with factory() as session:
        found = [p.id for p in catalog_service.product_candidates(session, "קפה שחור טחון")]
    assert found == [kept]


def test_the_match_log(
    factory: sessionmaker[Session], chain: uuid.UUID, caplog: pytest.LogCaptureFixture
) -> None:
    _product(factory, "שוקולד חלב אגוזים")
    _product(factory, "שוקולד חלב שקדים")
    caplog.clear()
    with caplog.at_level("INFO", logger="app.matching"):
        result = _match(factory, "שוקולד חלב", chain)
    [record] = [r for r in caplog.records if r.getMessage() == "matching_match"]
    assert (record.state, record.path, record.source) == (  # type: ignore[attr-defined]
        "uncertain",
        "text",
        "receipt",
    )
    first, second = result.candidates
    assert record.score == first.score  # type: ignore[attr-defined]
    assert record.gap == pytest.approx(first.score - second.score, abs=0.002)  # type: ignore[attr-defined]
    assert "שוקולד" not in str(record.__dict__)


def test_many_products_use_the_index(factory: sessionmaker[Session], engine: Engine) -> None:
    with factory() as session:
        catalog_service.ensure_products_by_barcode(
            session,
            [ProductRecord(f"72900{n:08d}", f"מוצר {n}", None, None, False) for n in range(500)],
            now=NOW,
        )
        session.commit()
    with factory() as session:
        found = catalog_service.product_candidates(session, "מוצר 1")
    assert len(found) == catalog_service.MAX_CANDIDATES
    assert found[0].similarity >= found[-1].similarity


def test_a_proposed_product_keeps_the_barcode(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    result = _match(factory, "משחת שיניים 75 מל", chain, "7290000000026")
    assert result.state == "new_product_proposal"
    [proposed] = _rows(engine, "SELECT * FROM products")
    assert (proposed["id"], proposed["barcode"]) == (result.product_id, "7290000000026")
    # A price file with the barcode later finds that product, and creates no other.
    with factory() as session:
        ids = catalog_service.ensure_products_by_barcode(
            session, [ProductRecord("7290000000026", "משחת שיניים", None, None, False)], now=NOW
        )
        session.commit()
    assert ids == {"7290000000026": result.product_id}
    assert _count(engine, "products") == 1


def test_propose_a_product_whose_barcode_exists(factory: sessionmaker[Session]) -> None:
    existing = _product(factory, "משחת שיניים", "7290000000026")
    with factory() as session:
        found = catalog_service.propose_product(
            session, "משחת שיניים 75 מל", Decimal(75), "ml", barcode="7290000000026", now=NOW
        )
        session.commit()
    assert found == existing


def test_a_text_with_no_letters_is_unmatched(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    _product(factory, "חלב")
    for _ in range(2):
        assert _match(factory, "***", chain) == UNMATCHED
        assert _match(factory, "* - *", chain, "123") == UNMATCHED
    assert (_aliases(engine), _count(engine, "products")) == ([], 1)


def test_a_proposed_product_is_reused(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    first = _match(factory, "משחת שיניים 75 מל", chain)
    assert first.state == "new_product_proposal"
    with engine.begin() as conn:
        # Its name no longer near the alias: no candidate at all.
        conn.execute(
            text("UPDATE products SET name = 'זזז', name_norm = 'זזז' WHERE id = :id"),
            {"id": first.product_id},
        )
    again = _match(factory, "משחת שיניים 75 מל", chain)
    assert (again.state, again.product_id, again.alias_id) == (
        "new_product_proposal",
        first.product_id,
        first.alias_id,
    )
    assert _count(engine, "products") == 1


def test_the_trigram_threshold_is_restored(factory: sessionmaker[Session]) -> None:
    _product(factory, "חלב")
    with factory() as session:
        session.execute(text("SELECT similarity('a', 'a')"))  # loads pg_trgm
        session.execute(text("SET pg_trgm.similarity_threshold = 0.5"))
        catalog_service.product_candidates(session, "חלב")
        value = session.execute(text("SHOW pg_trgm.similarity_threshold")).scalar_one()
        session.rollback()
    assert float(value) == 0.5


def test_median_prices(factory: sessionmaker[Session], engine: Engine) -> None:
    chain_id, store_a = _store(factory, code="101")
    _, store_b = _store(factory, code="102")
    _, store_c = _store(factory, code="103")
    milk = _product(factory, "חלב 1 ליטר")
    cheese = _product(factory, "גבינה במשקל")
    rows = [
        (milk, store_a, "regular", 500, "unit"),
        (milk, store_b, "regular", 900, "unit"),
        (milk, store_c, "regular", 700, "unit"),
        (milk, store_a, "promo", 100, "unit"),
        (milk, store_b, "club", 150, "unit"),
        (cheese, store_a, "regular", 6600, "kg"),
    ]
    with engine.begin() as conn:
        for product_id, store_id, price_type, agorot, per in rows:
            conn.execute(
                text(
                    "INSERT INTO price_observations (id, product_id, store_id, chain_id, source, "
                    "price_type, unit_price_agorot, per, observed_at, status, "
                    "has_personal_discount, created_at) VALUES (:id, :p, :s, :c, "
                    "'official_file', :t, :a, :per, now(), 'valid', false, now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "p": product_id,
                    "s": store_id,
                    "c": chain_id,
                    "t": price_type,
                    "a": agorot,
                    "per": per,
                },
            )
    _refresh(factory)
    with factory() as session:
        assert pricing_service.median_prices(session, [milk, cheese]) == {milk: 700}
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM price_observations WHERE store_id = :s"), {"s": store_c})
    _refresh(factory)
    with factory() as session:
        # Two stores: (500 + 900) / 2.
        assert pricing_service.median_prices(session, [milk]) == {milk: 700}


# --- the guards of a settled alias ---


@pytest.mark.parametrize("state", ["final", "disputed"])
def test_upsert_alias_leaves_a_settled_alias(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID, state: str
) -> None:
    coffee = _product(factory, "קפה שחור טחון")
    tea = _product(factory, "תה ירוק")
    first = _match(factory, "קפה שחור", chain)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE product_aliases SET state = :s WHERE id = :id"),
            {"s": state, "id": first.alias_id},
        )
    before = _aliases(engine)
    with factory() as session:
        alias = catalog_service.upsert_alias(
            session, chain, "קפה שחור", None, "certain", tea, Decimal("0.9"), now=NOW
        )
        session.commit()
    assert (alias.id, alias.state, alias.product_id) == (first.alias_id, state, coffee)
    assert alias.confidence == before[0]["confidence"]
    assert _aliases(engine) == before


@pytest.mark.parametrize("state", ["final", "disputed"])
def test_a_settled_alias_found_late_is_not_changed(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    _product(factory, "שוקולד חלב אגוזים")
    _product(factory, "שוקולד חלב שקדים")
    first = _match(factory, "שוקולד חלב", chain)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE product_aliases SET state = :s WHERE id = :id"),
            {"s": state, "id": first.alias_id},
        )
    before = (_aliases(engine), _candidates(engine), _count(engine, "products"))
    # As if it was settled by another transaction after it was looked up.
    monkeypatch.setattr(catalog_service, "alias_by_key", lambda *_a, **_k: None)
    caplog.clear()
    with caplog.at_level("INFO", logger="app.matching"):
        result = _match(factory, "שוקולד חלב", chain)
    assert (result.state, result.product_id, result.alias_id) == (
        state,
        first.product_id,
        first.alias_id,
    )
    assert (_aliases(engine), _candidates(engine), _count(engine, "products")) == before
    [record] = [r for r in caplog.records if r.getMessage() == "matching_match"]
    assert record.path == "memory"  # type: ignore[attr-defined]


def test_a_settled_alias_with_a_barcode_is_logged_as_memory(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _product(factory, "חלב", "7290000000001")
    first = _match(factory, "חלב 3%", chain, "7290000000001")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE product_aliases SET state = 'final' WHERE id = :id"),
            {"id": first.alias_id},
        )
    caplog.clear()
    with caplog.at_level("INFO", logger="app.matching"):
        result = _match(factory, "חלב 3%", chain, "7290000000001")
    assert (result.state, result.alias_id) == ("final", first.alias_id)
    [record] = [r for r in caplog.records if r.getMessage() == "matching_match"]
    assert record.path == "memory"  # type: ignore[attr-defined]


# --- SM-1 ---


def _snapshot(engine: Engine) -> tuple[Any, ...]:
    return tuple(
        _rows(engine, f"SELECT * FROM {table} ORDER BY 1")  # noqa: S608
        for table in ("products", "product_aliases", "match_candidates")
    )


def test_eval_matching(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID, capsys: Any
) -> None:
    # barcode: (product name, the chain's alias text)
    names = {
        "7290000000001": ("קפה שחור טחון 200 גרם", "קפה שחור טחון 200ג"),
        "7290000000002": ("משחת שיניים מלבינה 75 מל", "משחת שיניים מלבינה 75מל"),
        "7290000000003": ("נייר טואלט רך 32 יחידות", "נייר טואלט רך 32 יח"),
        # Named after this very alias: skipped, it would give the answer away.
        "7290000000004": ("גבינה צהובה 200 גרם", "גבינה צהובה 200 גרם"),
    }
    for code, (name, _) in names.items():
        _product(factory, name, code)
    with factory() as session:
        items = [(alias, code) for code, (_, alias) in names.items()]
        matching_service.match_barcodes(session, chain, items)
        session.commit()
    before = _snapshot(engine)

    with factory() as session:
        report = eval_matching.evaluate(session, 500, 42)
    assert (report["samples"], report["skipped_same_name"]) == (3, 1)
    assert report["certain"] == report["certain_correct"] == 3
    assert report["precision"] == 1.0
    assert (report["uncertain"], report["new_product_proposals"]) == (0, 0)
    assert report["recall_at_3"] == 1.0
    assert _snapshot(engine) == before

    table = report["thresholds"]
    assert [row["threshold"] for row in table] == [
        0.5,
        0.55,
        0.6,
        0.65,
        0.7,
        0.75,
        0.8,
        0.85,
        0.9,
        0.95,
    ]
    assert all(
        (row["certain"], row["precision"], row["coverage"]) == (3, 1.0, 1.0) for row in table
    )

    with factory() as session:
        sampled = eval_matching.evaluate(session, 2, 42)
    assert sampled["samples"] + sampled["skipped_same_name"] == 2

    assert eval_matching.run(["--limit", "500"], factory) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["samples"], printed["precision"], len(printed["thresholds"])) == (3, 1.0, 10)
    assert _snapshot(engine) == before


def test_eval_matching_samples_the_same_aliases(
    factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    items = [(f"מוצר בדוי {n}", f"72900{n:08d}") for n in range(20)]
    for name, code in items:
        _product(factory, name, code)
    with factory() as session:
        matching_service.match_barcodes(session, chain, items)
        session.commit()
    with factory() as session:
        first = catalog_service.sample_certain_barcode_aliases(session, 5, "42")
        again = catalog_service.sample_certain_barcode_aliases(session, 5, "42")
        other = catalog_service.sample_certain_barcode_aliases(session, 5, "7")
    assert first == again
    assert len(first) == 5
    assert first != other


def test_the_eval_with_no_aliases(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        report = eval_matching.evaluate(session, 500, 42)
    assert (report["samples"], report["precision"], report["recall_at_3"]) == (0, None, None)


# --- the migration ---


def test_candidates_migration_roundtrip(db_url: str) -> None:
    url = create_database(db_url, "cw_candidates_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    try:
        command.upgrade(cfg, "0011")
        assert "match_candidates" not in inspect(eng).get_table_names()
        command.upgrade(cfg, "0012")
        with eng.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM match_candidates")).scalar_one() == 0
        with eng.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO products (id, name, name_norm, is_weighted, status, created_at) "
                    "VALUES (:id, 'n', 'n', false, 'proposed', now())"
                ),
                {"id": uuid.uuid4()},
            )
        with pytest.raises(RuntimeError, match="proposed or merged_into"):
            command.downgrade(cfg, "0011")
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM products"))
        command.downgrade(cfg, "0011")
        tables = set(inspect(eng).get_table_names())
        assert "match_candidates" not in tables
        assert {"products", "product_aliases"} <= tables
    finally:
        eng.dispose()


def test_models_match_the_migrations(text_url: str) -> None:
    command.check(alembic_config(text_url))
