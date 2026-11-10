"""Matching a price file's items with no barcode (Story 3.6), against Postgres, with no network.

Every product, barcode, name and price here is invented.
"""

import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import make_engine
from app.modules.catalog import service as catalog_service
from app.modules.catalog.service import ProductRecord
from app.modules.ingestion import prices
from app.modules.ingestion.decode import decode_xml
from app.modules.ingestion.prices import SOURCE_REF_ATTRIBUTE
from app.modules.matching import service as matching_service
from app.modules.matching.service import FileItem, MatchContext, MatchResult
from app.modules.pricing import service as pricing_service
from tests.integration.pg import alembic_config, create_database
from tests.integration.test_prices import _item, _price_file, _store

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
TOMATO_BARCODE = "1000000000101"


@pytest.fixture(scope="module")
def file_url(db_url: str) -> str:
    """A database of its own: these tests truncate and count rows."""
    url = create_database(db_url, "cw_file_matching")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(file_url: str) -> Iterator[Engine]:
    eng = make_engine(file_url)
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


@pytest.fixture
def store(factory: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    """(chain_id, store_id) of store 101 of the fictional chain."""
    return _store(factory)  # type: ignore[no-any-return]


def _internal(price: str, name: str, weighted: str = "0", code: str = "7001") -> str:
    return _item(code, price, name, item_type="0", weighted=weighted)


def _prices(
    factory: sessionmaker[Session], chain_id: uuid.UUID, data: bytes, now: datetime = NOW
) -> int:
    root = decode_xml(data)
    root.set(SOURCE_REF_ATTRIBUTE, "PriceFull-test.gz")
    with factory() as session:
        count = prices.price_handler(lambda: now)(session, chain_id, root)
        session.commit()
    return count


def _product(factory: sessionmaker[Session], name: str, barcode: str) -> uuid.UUID:
    with factory() as session:
        ids = catalog_service.ensure_products_by_barcode(
            session, [ProductRecord(barcode, name, None, None, False)], now=NOW
        )
        session.commit()
    return ids[barcode]


def _rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql), params)]


def _observations(engine: Engine) -> list[dict[str, Any]]:
    # ids are UUIDv7: in insertion order.
    return _rows(engine, "SELECT * FROM price_observations ORDER BY id")


_FILE_ITEM_KEYS = (
    "items",
    "reused",
    "matched",
    "certain",
    "uncertain",
    "proposed",
    "final",
    "disputed",
    "unmatched",
)
# Every count at 0 in matching_file_items: a test sets the ones it expects.
ZERO = dict.fromkeys(_FILE_ITEM_KEYS, 0)


def _file_items_log(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        {key: getattr(record, key) for key in _FILE_ITEM_KEYS}
        for record in caplog.records
        if record.getMessage() == "matching_file_items"
    ]


def _context(price: int | None, weighted: bool = False) -> MatchContext:
    # _item writes UnitQty יחידה and Quantity 1.
    return MatchContext("official_file", price, weighted, Decimal(1), "unit")


def _ingestion_log(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    [record] = [r for r in caplog.records if r.getMessage() == "ingestion_prices"]
    return record.__dict__


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, MatchContext | None]]:
    """The (alias_text, context) of each call to matching.service.match."""
    calls: list[tuple[str, MatchContext | None]] = []
    real = matching_service.match

    def recording(
        session: Session,
        alias_text: str,
        chain_id: uuid.UUID,
        barcode: str | None = None,
        context: MatchContext | None = None,
        now: datetime | None = None,
        *,
        count: bool = True,
    ) -> MatchResult:
        calls.append((alias_text, context))
        return real(session, alias_text, chain_id, barcode, context, now, count=count)

    monkeypatch.setattr(matching_service, "match", recording)
    return calls


# --- the matrix ---


def test_an_internal_item_that_matches(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, store_id = store
    tomato = _product(factory, "עגבניות שרי במשקל", TOMATO_BARCODE)
    assert _prices(factory, chain_id, _price_file(_internal("12.90", "עגבניות שרי במשקל"))) == 1

    [alias] = _rows(engine, "SELECT * FROM product_aliases")
    assert (alias["state"], alias["product_id"], alias["barcode"]) == ("certain", tomato, None)
    [obs] = _observations(engine)
    assert (obs["product_id"], obs["price_type"], obs["unit_price_agorot"], obs["per"]) == (
        tomato,
        "regular",
        1290,
        "unit",
    )
    with factory() as session:
        pricing_service.refresh_current_prices(session)
        session.commit()
        current = pricing_service.current_prices(session, store_id)
    assert (current[tomato].unit_price_agorot, current[tomato].per) == (1290, "unit")


def test_a_new_internal_item(engine: Engine, factory: sessionmaker[Session], store: Any) -> None:
    chain_id, _ = store
    _product(factory, "שוקולד מריר", "1000000000102")
    assert _prices(factory, chain_id, _price_file(_internal("7.90", "קולרבי אורגני"))) == 1

    [product] = _rows(engine, "SELECT * FROM products WHERE barcode IS NULL")
    assert (product["status"], product["name"]) == ("proposed", "קולרבי אורגני")
    [alias] = _rows(engine, "SELECT * FROM product_aliases")
    assert (alias["state"], alias["product_id"]) == ("uncertain", product["id"])
    [obs] = _observations(engine)
    assert (obs["product_id"], obs["unit_price_agorot"]) == (product["id"], 790)


def test_the_same_item_in_a_second_file(
    engine: Engine,
    factory: sessionmaker[Session],
    store: Any,
    spy: list[tuple[str, MatchContext | None]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    chain_id, _ = store
    _prices(factory, chain_id, _price_file(_internal("7.90", "קולרבי אורגני")))
    assert len(spy) == 1
    [product] = _rows(engine, "SELECT id FROM products")

    caplog.clear()
    with caplog.at_level(logging.INFO):
        later = NOW + timedelta(hours=6)
        _prices(factory, chain_id, _price_file(_internal("7.90", "קולרבי אורגני")), later)
    assert len(spy) == 1  # match was not called again
    [entry] = _file_items_log(caplog)
    assert entry == ZERO | {"items": 1, "reused": 1}
    assert len(_rows(engine, "SELECT id FROM products")) == 1
    assert len(_observations(engine)) == 1  # the same price: no new observation

    _prices(factory, chain_id, _price_file(_internal("8.50", "קולרבי אורגני")), later)
    assert len(spy) == 1
    assert [(o["product_id"], o["unit_price_agorot"]) for o in _observations(engine)] == [
        (product["id"], 790),
        (product["id"], 850),
    ]


def test_a_text_that_cleans_to_nothing(
    engine: Engine,
    factory: sessionmaker[Session],
    store: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    chain_id, _ = store
    with caplog.at_level(logging.INFO):
        assert _prices(factory, chain_id, _price_file(_internal("5.00", "***"))) == 0
    assert _rows(engine, "SELECT * FROM products") == []
    assert _rows(engine, "SELECT * FROM product_aliases") == []
    assert _observations(engine) == []
    log = _ingestion_log(caplog)
    assert (log["internal"], log["internal_priced"], log["internal_unmatched"]) == (1, 0, 1)
    assert "skipped_no_barcode" not in log


def test_a_weighted_internal_item(
    engine: Engine,
    factory: sessionmaker[Session],
    store: Any,
    spy: list[tuple[str, MatchContext | None]],
) -> None:
    chain_id, _ = store
    _prices(factory, chain_id, _price_file(_internal("12.90", "תפוחי עץ בדויים", weighted="1")))
    [(_, context)] = spy
    assert context == _context(None, weighted=True)
    [obs] = _observations(engine)
    assert (obs["unit_price_agorot"], obs["per"]) == (1290, "kg")


def test_two_internal_items_of_one_name(
    engine: Engine,
    factory: sessionmaker[Session],
    store: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    chain_id, _ = store
    data = _price_file(
        _internal("5.00", "בננה בדויה", code="7001"), _internal("6.00", "בננה בדויה", code="7002")
    )
    with caplog.at_level(logging.INFO):
        assert _prices(factory, chain_id, data) == 1
    assert [o["unit_price_agorot"] for o in _observations(engine)] == [500]
    assert len(_rows(engine, "SELECT * FROM product_aliases")) == 1
    log = _ingestion_log(caplog)
    assert (log["internal"], log["skipped_duplicate_name"]) == (1, 1)
    assert "skipped_duplicate" not in log


@pytest.mark.parametrize("internal_first", [False, True])
def test_a_barcode_item_and_an_internal_item_of_one_product(
    engine: Engine,
    factory: sessionmaker[Session],
    store: Any,
    caplog: pytest.LogCaptureFixture,
    internal_first: bool,
) -> None:
    chain_id, _ = store
    tomato = _product(factory, "עגבניות שרי במשקל", TOMATO_BARCODE)
    items = [
        _item(TOMATO_BARCODE, "13.90", "עגבניות שרי במשקל"),
        _internal("12.90", "עגבניות שרי במשקל"),
    ]
    data = _price_file(*(reversed(items) if internal_first else items))
    with caplog.at_level(logging.INFO):
        assert _prices(factory, chain_id, data) == 1
    log = _ingestion_log(caplog)
    assert (log["internal_same_product"], log["internal_priced"]) == (1, 0)
    # One observation, by the item with the barcode.
    [obs] = _observations(engine)
    assert (obs["product_id"], obs["unit_price_agorot"]) == (tomato, 1390)
    aliases = _rows(engine, "SELECT barcode, product_id FROM product_aliases ORDER BY barcode")
    assert aliases == [
        {"barcode": TOMATO_BARCODE, "product_id": tomato},
        {"barcode": None, "product_id": tomato},
    ]


def test_the_unit_price_is_in_the_context(
    factory: sessionmaker[Session],
    store: Any,
    spy: list[tuple[str, MatchContext | None]],
) -> None:
    chain_id, _ = store
    _prices(factory, chain_id, _price_file(_internal("5.00", "חסה בדויה")))
    assert spy == [("חסה בדויה", _context(500))]


def test_a_proposed_product_has_the_items_weight_and_pack(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, _ = store
    weighted = (
        "<Item><ItemCode>7001</ItemCode><ItemType>0</ItemType><ItemName>קולרבי אורגני</ItemName>"
        "<UnitQty>קילוגרם</UnitQty><Quantity>1</Quantity><bIsWeighted>1</bIsWeighted>"
        "<ItemPrice>12.90</ItemPrice></Item>"
    )
    _prices(factory, chain_id, _price_file(weighted))
    [product] = _rows(engine, "SELECT * FROM products")
    assert (product["status"], product["is_weighted"]) == ("proposed", True)
    assert (product["pack_size"], product["pack_unit"]) == (Decimal(1), "kg")
    [obs] = _observations(engine)
    assert (obs["product_id"], obs["per"]) == (product["id"], "kg")


def test_an_alias_of_a_merged_product_is_not_reused(
    engine: Engine,
    factory: sessionmaker[Session],
    store: Any,
    spy: list[tuple[str, MatchContext | None]],
) -> None:
    chain_id, _ = store
    _prices(factory, chain_id, _price_file(_internal("7.90", "קולרבי אורגני")))
    with engine.begin() as conn:
        conn.execute(text("UPDATE products SET status = 'merged_into'"))
    _prices(factory, chain_id, _price_file(_internal("8.50", "קולרבי אורגני")))
    # Matched again: the merged product is not a candidate, so another is proposed.
    assert len(spy) == 2
    merged, proposed = _rows(engine, "SELECT id, status FROM products ORDER BY id")
    assert (merged["status"], proposed["status"]) == ("merged_into", "proposed")
    assert [o["product_id"] for o in _observations(engine)] == [merged["id"], proposed["id"]]


def test_two_chains_with_one_internal_name(
    engine: Engine,
    factory: sessionmaker[Session],
    spy: list[tuple[str, MatchContext | None]],
) -> None:
    first, _ = _store(factory)
    second, _ = _store(factory, chain_code="7290000000002")
    _prices(factory, first, _price_file(_internal("7.90", "קולרבי אורגני")))
    _prices(factory, second, _price_file(_internal("7.90", "קולרבי אורגני")))
    # An alias is a chain's: the second chain matches its own.
    assert len(spy) == 2
    aliases = _rows(engine, "SELECT chain_id FROM product_aliases WHERE barcode IS NULL")
    assert sorted(a["chain_id"] for a in aliases) == sorted([first, second])


# --- the acceptance criteria ---


def test_an_item_with_a_barcode_is_matched_by_it(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, _ = store
    known = _product(factory, "חלב בדוי", "1000000000103")
    data = _price_file(
        _item("1000000000103", "6.90", "חלב בדוי בשם אחר"), _item("1000000000104", "9.50", "לחם")
    )
    assert _prices(factory, chain_id, data) == 2
    products = {p["barcode"]: p for p in _rows(engine, "SELECT * FROM products")}
    assert products["1000000000103"]["id"] == known
    assert products["1000000000103"]["name"] == "חלב בדוי"
    assert products["1000000000104"]["status"] == "active"
    assert {o["product_id"] for o in _observations(engine)} == {
        known,
        products["1000000000104"]["id"],
    }


def test_match_file_items_in_order(
    factory: sessionmaker[Session], store: Any, caplog: pytest.LogCaptureFixture
) -> None:
    chain_id, _ = store
    tomato = _product(factory, "עגבניות שרי במשקל", TOMATO_BARCODE)
    with factory() as session, caplog.at_level(logging.INFO):
        ids = matching_service.match_file_items(
            session,
            chain_id,
            [
                FileItem("***"),
                FileItem("עגבניות שרי במשקל", 1290),
                FileItem("   ", 100),
                FileItem("קולרבי אורגני"),
            ],
            now=NOW,
        )
        session.commit()
    assert ids[0] is None and ids[2] is None
    assert ids[1] == tomato
    assert ids[3] is not None and ids[3] != tomato
    [entry] = _file_items_log(caplog)
    assert entry == ZERO | {
        "items": 4,
        "matched": 2,
        "certain": 1,
        "proposed": 1,
        "unmatched": 2,
    }


def test_match_file_items_reuses_an_alias_for_a_name_twice(
    factory: sessionmaker[Session],
    store: Any,
    spy: list[tuple[str, MatchContext | None]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    chain_id, _ = store
    _prices(factory, chain_id, _price_file(_internal("7.90", "קולרבי אורגני")))
    assert len(spy) == 1
    caplog.clear()
    with factory() as session, caplog.at_level(logging.INFO):
        ids = matching_service.match_file_items(
            session,
            chain_id,
            [FileItem("קולרבי אורגני", 790), FileItem(" קולרבי  אורגני", 800)],
            now=NOW,
        )
    assert len(spy) == 1  # match was not called
    assert ids[0] is not None and ids == [ids[0], ids[0]]
    [entry] = _file_items_log(caplog)
    assert entry == ZERO | {"items": 2, "reused": 2}
