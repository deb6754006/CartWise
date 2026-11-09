"""Prices and promotions (Story 3.4), against Postgres, with fake adapters: no network.

Every product, barcode and price here is invented.
"""

import gzip
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
from app.modules.catalog.service import StoreRecord
from app.modules.ingestion import prices, service
from app.modules.ingestion.decode import decode_xml
from app.modules.ingestion.prices import SOURCE_REF_ATTRIBUTE
from app.modules.ingestion.service import RunSummary, ingest_chain
from app.modules.pricing import service as pricing_service
from tests.integration.pg import alembic_config, create_database
from tests.integration.test_ingestion import CODE, PRICE, PROMO, FakeAdapter, _good_files

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
MILK, BREAD, CHEESE = "1000000000001", "1000000000002", "1000000000003"
OTHER_CODE = "7290000000002"


@pytest.fixture(scope="module")
def prices_url(db_url: str) -> str:
    """A database of its own: these tests truncate and count rows."""
    url = create_database(db_url, "cw_prices")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(prices_url: str) -> Iterator[Engine]:
    eng = make_engine(prices_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE match_candidates, product_aliases, promotion_products, promotions, "
                "price_observations, products, "
                "ingestion_alerts, "
                "ingestion_files, ingestion_runs, stores, user_clubs, clubs, chains"
            )
        )
        conn.execute(text("REFRESH MATERIALIZED VIEW current_prices"))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _store(factory: sessionmaker[Session], chain_code: str = CODE, code: str = "101") -> Any:
    with factory() as session:
        chain_id = catalog_service.ensure_chain(session, chain_code, "רשת בדויה")
        state = catalog_service.upsert_store(
            session,
            chain_id,
            StoreRecord(code, "1", "סניף בדוי", "רחוב בדוי 1", "3000", None, 1),
            NOW,
        )
        session.commit()
    return chain_id, state.id


@pytest.fixture
def store(factory: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    """(chain_id, store_id) of store 101 of the fictional chain."""
    return _store(factory)  # type: ignore[no-any-return]


def _item(
    code: str,
    price: str,
    name: str = "מוצר בדוי",
    item_type: str = "1",
    weighted: str = "0",
    time: str = "2026-11-01 08:00:00",
) -> str:
    return (
        f"<Item><ItemCode>{code}</ItemCode><ItemType>{item_type}</ItemType>"
        f"<ItemName>{name}</ItemName><UnitQty>יחידה</UnitQty><Quantity>1</Quantity>"
        f"<bIsWeighted>{weighted}</bIsWeighted><ItemPrice>{price}</ItemPrice>"
        f"<PriceUpdateTime>{time}</PriceUpdateTime></Item>"
    )


def _price_file(*items: str, store: str = "101") -> bytes:
    return (
        f"<Root><ChainId>{CODE}</ChainId><SubChainId>1</SubChainId><StoreId>{store}</StoreId>"
        f"<Items>{''.join(items)}</Items></Root>"
    ).encode()


def _promotion(
    gov_id: str,
    *items: str,
    club: str = "0",
    coupon: str = "0",
    start: str = "2026-11-01T00:00:00.000",
    end: str = "2026-12-31T23:59:00.000",
    description: str = "מבצע בדוי",
) -> str:
    return (
        f"<Promotion><PromotionId>{gov_id}</PromotionId>"
        f"<PromotionDescription>{description}</PromotionDescription>"
        f"<PromotionStartDateTime>{start}</PromotionStartDateTime>"
        f"<PromotionEndDateTime>{end}</PromotionEndDateTime><ClubID>{club}</ClubID>"
        f"<AdditionalIsCoupon>{coupon}</AdditionalIsCoupon><Groups><Group><PromotionItems>"
        f"{''.join(items)}</PromotionItems></Group></Groups></Promotion>"
    )


def _promo_item(
    code: str, reward: str = "3", min_qty: str = "1", rate: str = "", price: str = ""
) -> str:
    return (
        f"<PromotionItem><ItemCode>{code}</ItemCode><ItemType>1</ItemType>"
        f"<RewardType>{reward}</RewardType><MinQty>{min_qty}</MinQty>"
        f"<DiscountRate>{rate}</DiscountRate><DiscountedPrice>{price}</DiscountedPrice>"
        "</PromotionItem>"
    )


def _promo_file(*promotions: str, store: str = "101") -> bytes:
    return (
        f"<Root><ChainId>{CODE}</ChainId><StoreId>{store}</StoreId>"
        f"<Promotions>{''.join(promotions)}</Promotions></Root>"
    ).encode()


def _handle(
    factory: sessionmaker[Session],
    handler: prices.FileHandler,
    chain_id: uuid.UUID,
    data: bytes,
    name: str = "PriceFull-test.gz",
) -> int:
    root = decode_xml(data)
    root.set(SOURCE_REF_ATTRIBUTE, name)
    with factory() as session:
        count = handler(session, chain_id, root)
        session.commit()
    return count


def _prices(
    factory: sessionmaker[Session], chain_id: uuid.UUID, data: bytes, now: datetime = NOW
) -> int:
    return _handle(factory, prices.price_handler(lambda: now), chain_id, data)


def _promos(
    factory: sessionmaker[Session], chain_id: uuid.UUID, data: bytes, now: datetime = NOW
) -> int:
    return _handle(factory, prices.promo_handler(lambda: now), chain_id, data, "PromoFull-t.gz")


def _refresh(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        pricing_service.refresh_current_prices(session)
        session.commit()


def _rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql), params)]


def _observations(engine: Engine) -> list[dict[str, Any]]:
    return _rows(
        engine,
        "SELECT o.*, p.barcode FROM price_observations o JOIN products p ON p.id = o.product_id "
        "ORDER BY p.barcode, o.id",  # ids are UUIDv7: in insertion order,
    )


def _current(factory: sessionmaker[Session], store_id: uuid.UUID) -> dict[str, tuple[int, str]]:
    """The store's current prices, by barcode, or by name for a product with no barcode."""
    with factory() as session:
        current = pricing_service.current_prices(session, store_id)
        keys = {
            row[0]: row[1] if row[1] is not None else row[2]
            for row in session.execute(text("SELECT id, barcode, name FROM products")).all()
        }
    return {keys[k]: (v.unit_price_agorot, v.per) for k, v in current.items()}


def _active(
    factory: sessionmaker[Session], store_id: uuid.UUID, at: datetime = NOW
) -> dict[str, pricing_service.ActivePromotion]:
    with factory() as session:
        return {
            p.gov_promotion_id: p
            for p in pricing_service.active_promotions(session, [store_id], at)
        }


def _product_id(engine: Engine, barcode: str) -> uuid.UUID:
    [row] = _rows(engine, "SELECT id FROM products WHERE barcode = :b", b=barcode)
    return row["id"]  # type: ignore[no-any-return]


# --- PriceFull ---


def test_a_first_price_file(engine: Engine, factory: sessionmaker[Session], store: Any) -> None:
    chain_id, store_id = store
    data = _price_file(
        _item(MILK, "13.90", "חלב בדוי"),
        _item(BREAD, "9.50", "לחם בדוי"),
        _item(CHEESE, "66.00", "גבינה בדויה", weighted="1"),
        _item("7001", "7.90", "קולרבי אורגני", item_type="0"),
    )
    assert _prices(factory, chain_id, data) == 4

    # The item with an internal code is matched by its name (Story 3.6): nothing is near, so a
    # product is proposed for it.
    products = _rows(engine, "SELECT * FROM products ORDER BY barcode")
    assert [(p["barcode"], p["name"], p["status"]) for p in products] == [
        (MILK, "חלב בדוי", "active"),
        (BREAD, "לחם בדוי", "active"),
        (CHEESE, "גבינה בדויה", "active"),
        (None, "קולרבי אורגני", "proposed"),
    ]
    assert (products[0]["pack_size"], products[0]["pack_unit"]) == (Decimal(1), "unit")
    assert products[2]["is_weighted"] is True
    assert products[0]["name_norm"] == catalog_service.normalize_he("חלב בדוי")

    obs = _observations(engine)
    assert [(o["barcode"], o["unit_price_agorot"], o["per"]) for o in obs] == [
        (MILK, 1390, "unit"),
        (BREAD, 950, "unit"),
        (CHEESE, 6600, "kg"),
        (None, 790, "unit"),
    ]
    for o in obs:
        assert (o["source"], o["price_type"], o["status"]) == ("official_file", "regular", "valid")
        assert o["store_id"] == store_id
        assert o["chain_id"] == chain_id
        assert o["source_ref"] == "PriceFull-test.gz"
        assert o["contributor_user_id"] is None
        assert o["has_personal_discount"] is False
        assert o["created_at"] == NOW
        # 08:00 in Israel, in winter.
        assert o["observed_at"] == datetime(2026, 11, 1, 6, 0, tzinfo=UTC)

    assert _current(factory, store_id) == {}  # until the view is refreshed
    _refresh(factory)
    assert _current(factory, store_id) == {
        MILK: (1390, "unit"),
        BREAD: (950, "unit"),
        CHEESE: (6600, "kg"),
        "קולרבי אורגני": (790, "unit"),
    }


def test_the_same_prices_again(engine: Engine, factory: sessionmaker[Session], store: Any) -> None:
    chain_id, _ = store
    _prices(factory, chain_id, _price_file(_item(MILK, "13.90"), _item(BREAD, "9.50")))
    later = _price_file(_item(MILK, "13.90", time="2026-11-02 08:00:00"), _item(BREAD, "9.5"))
    assert _prices(factory, chain_id, later, NOW + timedelta(hours=6)) == 2
    assert len(_observations(engine)) == 2


def test_a_price_that_changed(engine: Engine, factory: sessionmaker[Session], store: Any) -> None:
    chain_id, store_id = store
    _prices(factory, chain_id, _price_file(_item(MILK, "13.90"), _item(BREAD, "9.50")))
    changed = _price_file(_item(MILK, "12.90", time="2026-11-02 08:00:00"), _item(BREAD, "9.50"))
    assert _prices(factory, chain_id, changed, NOW + timedelta(hours=6)) == 2

    milk = [o for o in _observations(engine) if o["barcode"] == MILK]
    assert [o["unit_price_agorot"] for o in milk] == [1390, 1290]
    assert milk[1]["observed_at"] == datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
    _refresh(factory)
    assert _current(factory, store_id)[MILK] == (1290, "unit")

    # And back: a new observation again, never an update.
    _prices(factory, chain_id, _price_file(_item(MILK, "13.90", time="2026-11-03 08:00:00")))
    milk = [o for o in _observations(engine) if o["barcode"] == MILK]
    assert [o["unit_price_agorot"] for o in milk] == [1390, 1290, 1390]
    _refresh(factory)
    assert _current(factory, store_id)[MILK] == (1390, "unit")


def test_per_changing_is_a_new_observation(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, _ = store
    _prices(factory, chain_id, _price_file(_item(CHEESE, "66.00")))
    _prices(factory, chain_id, _price_file(_item(CHEESE, "66.00", weighted="1")))
    assert [o["per"] for o in _observations(engine)] == ["unit", "kg"]


def test_an_older_update_time_does_not_go_back(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, store_id = store
    _prices(factory, chain_id, _price_file(_item(MILK, "13.90", time="2026-11-02 08:00:00")))
    _prices(factory, chain_id, _price_file(_item(MILK, "12.90", time="2026-11-01 08:00:00")))
    _refresh(factory)
    assert _current(factory, store_id)[MILK] == (1290, "unit")
    # So the next file with the same price writes nothing.
    assert _prices(factory, chain_id, _price_file(_item(MILK, "12.90"))) == 1
    assert len(_observations(engine)) == 2


def test_a_missing_or_future_update_time(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, _ = store
    data = _price_file(_item(MILK, "13.90", time=""), _item(BREAD, "9.50", time="2099-01-01"))
    _prices(factory, chain_id, data)
    assert [o["observed_at"] for o in _observations(engine)] == [NOW, NOW]


def test_a_weighted_item(engine: Engine, factory: sessionmaker[Session], store: Any) -> None:
    chain_id, _ = store
    _prices(factory, chain_id, _price_file(_item(CHEESE, "66.00", weighted="1")))
    [obs] = _observations(engine)
    assert (obs["per"], obs["unit_price_agorot"]) == ("kg", 6600)


def test_bad_prices_are_skipped(engine: Engine, factory: sessionmaker[Session], store: Any) -> None:
    chain_id, _ = store
    data = _price_file(
        _item("10000001", "abc"),
        _item("10000002", "0"),
        _item("10000003", "-1"),
        _item(MILK, "13.90"),
    )
    assert _prices(factory, chain_id, data) == 1
    assert [o["barcode"] for o in _observations(engine)] == [MILK]
    assert [p["barcode"] for p in _rows(engine, "SELECT barcode FROM products")] == [MILK]


def test_a_duplicate_item_in_a_file(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, _ = store
    assert _prices(factory, chain_id, _price_file(_item(MILK, "5.00"), _item(MILK, "6.00"))) == 1
    assert [o["unit_price_agorot"] for o in _observations(engine)] == [500]


def test_a_product_seen_in_another_chain(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, store_id = store
    other_chain, other_store = _store(factory, OTHER_CODE, "7")
    _prices(factory, chain_id, _price_file(_item(MILK, "13.90", "חלב בדוי")))
    _prices(factory, other_chain, _price_file(_item(MILK, "14.20", "שם אחר"), store="7"))

    [product] = _rows(engine, "SELECT id, name FROM products")
    assert product["name"] == "חלב בדוי"
    obs = _observations(engine)
    assert {o["product_id"] for o in obs} == {product["id"]}
    assert {(o["store_id"], o["unit_price_agorot"]) for o in obs} == {
        (store_id, 1390),
        (other_store, 1420),
    }


def test_a_barcode_with_leading_zeros_is_kept(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, _ = store
    _prices(factory, chain_id, _price_file(_item("00012345", "1.00"), _item("12345000", "2.00")))
    assert sorted(p["barcode"] for p in _rows(engine, "SELECT barcode FROM products")) == [
        "00012345",
        "12345000",
    ]


def test_an_unknown_store_fails_the_file(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, _ = store
    with pytest.raises(prices.UnknownStoreError, match="unknown store 999"):
        _prices(factory, chain_id, _price_file(_item(MILK, "13.90"), store="00999"))
    assert _rows(engine, "SELECT * FROM products") == []


def test_many_items_in_one_file(engine: Engine, factory: sessionmaker[Session], store: Any) -> None:
    chain_id, store_id = store
    items = [_item(f"{10000000 + n}", f"{n % 50 + 1}.90") for n in range(2500)]
    assert _prices(factory, chain_id, _price_file(*items)) == 2500
    assert _prices(factory, chain_id, _price_file(*items)) == 2500
    assert len(_observations(engine)) == 2500
    _refresh(factory)
    assert len(_current(factory, store_id)) == 2500


# --- PromoFull ---


@pytest.fixture
def products(factory: sessionmaker[Session], store: Any) -> None:
    chain_id, _ = store
    _prices(
        factory,
        chain_id,
        _price_file(_item(MILK, "13.90"), _item(BREAD, "9.50"), _item(CHEESE, "29.90")),
    )


def _club_name(engine: Engine, club_id: uuid.UUID | None) -> str | None:
    if club_id is None:
        return None
    [row] = _rows(engine, "SELECT name FROM clubs WHERE id = :id", id=club_id)
    return row["name"]  # type: ignore[no-any-return]


@pytest.mark.usefixtures("products")
def test_promotions(engine: Engine, factory: sessionmaker[Session], store: Any) -> None:
    chain_id, store_id = store
    data = _promo_file(
        # 2 for 20, for everyone.
        _promotion("1", _promo_item(MILK, "10", "2", price="20.00"), club="0"),
        # A fixed price for the club.
        _promotion(
            "2",
            _promo_item(BREAD, "3", price="24.90"),
            club="(2=מועדון קרפור אשראי|2=מועדון אפליקציה)",
        ),
        # A club expression with code 0, and an empty one: still a club.
        _promotion(
            "3",
            _promo_item(BREAD, "3", price="8.00"),
            club="(0=מועדון קרפור אשראי|0=מועדון אפליקציה)",
        ),
        _promotion("4", _promo_item(BREAD, "3", price="8.50"), club=""),
        # Every customer, and a percent.
        _promotion("5", _promo_item(CHEESE, "2", rate="5"), club="0 - כלל הלקוחות"),
        # By weight, MinQty 0.010.
        _promotion("6", _promo_item(CHEESE, "3", "0.010", price="25.00")),
    )
    assert _promos(factory, chain_id, data) == 6

    active = _active(factory, store_id)
    assert set(active) == {"1", "2", "3", "4", "5", "6"}
    milk, bread, cheese = (_product_id(engine, b) for b in (MILK, BREAD, CHEESE))

    two_for = active["1"]
    assert (two_for.kind, two_for.min_qty, two_for.bundle_price_agorot) == (
        "multi_buy",
        Decimal(2),
        2000,
    )
    assert two_for.club_id is None
    assert two_for.product_ids == (milk,)
    assert two_for.description == "מבצע בדוי"
    assert two_for.starts_at == datetime(2026, 10, 31, 22, 0, tzinfo=UTC)
    assert two_for.ends_at == datetime(2026, 12, 31, 21, 59, tzinfo=UTC)
    assert (two_for.store_id, two_for.chain_id) == (store_id, chain_id)

    fixed = active["2"]
    assert (fixed.kind, fixed.min_qty, fixed.bundle_price_agorot) == ("fixed_price", 1, 2490)
    assert _club_name(engine, fixed.club_id) == "מועדון רשת בדויה"
    assert active["3"].club_id == active["4"].club_id == fixed.club_id
    # One club for the chain.
    assert len(_rows(engine, "SELECT id FROM clubs WHERE chain_id = :c", c=chain_id)) == 1

    percent = active["5"]
    assert (percent.kind, percent.percent, percent.bundle_price_agorot) == (
        "percent",
        Decimal(5),
        None,
    )
    assert percent.club_id is None
    assert (active["6"].kind, active["6"].min_qty, active["6"].product_ids) == (
        "fixed_price",
        Decimal(1),
        (cheese,),
    )
    assert bread in active["2"].product_ids

    [row] = _rows(engine, "SELECT source, updated_at FROM promotions WHERE gov_promotion_id='1'")
    assert row == {"source": "official_file", "updated_at": NOW}


@pytest.mark.usefixtures("products")
def test_promotions_that_are_not_saved(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, store_id = store
    data = _promo_file(
        _promotion("coupon", _promo_item(MILK, price="5.00"), coupon="1"),
        _promotion("expired", _promo_item(MILK, price="5.00"), end="2026-11-02T00:00:00"),
        _promotion("unknown", _promo_item("99999999", price="5.00")),
        _promotion("no-end", _promo_item(MILK, price="5.00"), end=""),
        _promotion("no-price", _promo_item(MILK, "3")),
        # Ends before it starts.
        _promotion(
            "bad-dates",
            _promo_item(MILK, price="5.00"),
            start="2026-11-10T00:00:00",
            end="2026-11-05T00:00:00",
        ),
        _promotion("ok", _promo_item(MILK, price="5.00")),
    )
    assert _promos(factory, chain_id, data) == 1
    assert set(_active(factory, store_id)) == {"ok"}
    assert [r["gov_promotion_id"] for r in _rows(engine, "SELECT * FROM promotions")] == ["ok"]
    # No product is created from a promotion.
    assert len(_rows(engine, "SELECT id FROM products")) == 3


@pytest.mark.usefixtures("products")
def test_the_first_item_with_a_product_sets_the_kind(
    engine: Engine,
    factory: sessionmaker[Session],
    store: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    chain_id, store_id = store
    data = _promo_file(
        _promotion(
            "1",
            _promo_item("99999999", "10", "2", price="20.00"),
            _promo_item(MILK, "3", price="5.00"),
            # Another reward: left out of the promotion.
            _promo_item(BREAD, "10", "2", price="20.00"),
        ),
        # A percent: each item has a DiscountedPrice of its own, and the rate is what applies.
        _promotion(
            "2",
            _promo_item(MILK, "2", rate="10", price="12.51"),
            _promo_item(BREAD, "2", rate="10", price="8.55"),
            _promo_item(CHEESE, "3", price="5.00"),
        ),
    )
    with caplog.at_level("INFO", logger="app.ingestion"):
        _promos(factory, chain_id, data)
    active = _active(factory, store_id)
    one, two = active["1"], active["2"]
    assert (one.kind, one.bundle_price_agorot) == ("fixed_price", 500)
    assert one.product_ids == (_product_id(engine, MILK),)
    assert (two.kind, two.percent, two.bundle_price_agorot) == ("percent", Decimal(10), None)
    assert set(two.product_ids) == {_product_id(engine, MILK), _product_id(engine, BREAD)}
    [record] = [r for r in caplog.records if r.getMessage() == "ingestion_promotions"]
    assert record.skipped_mixed_reward_items == 2  # type: ignore[attr-defined]


@pytest.mark.usefixtures("products")
def test_a_promotion_saved_again_with_other_terms(
    factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, store_id = store
    club = _promo_file(
        _promotion("1", _promo_item(MILK, "3", price="5.00"), club="2", description="למועדון")
    )
    _promos(factory, chain_id, club)
    assert _active(factory, store_id)["1"].club_id is not None
    everyone = _promo_file(
        _promotion("1", _promo_item(MILK, "2", rate="10"), club="0", description="לכולם")
    )
    _promos(factory, chain_id, everyone, NOW + timedelta(hours=6))
    promo = _active(factory, store_id, NOW + timedelta(hours=6))["1"]
    assert promo.club_id is None
    assert (promo.kind, promo.percent, promo.bundle_price_agorot) == ("percent", Decimal(10), None)
    assert promo.description == "לכולם"


def test_a_promotion_file_with_no_known_product_fails(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, store_id = store
    _prices(factory, chain_id, _price_file(_item(MILK, "13.90")))
    _promos(factory, chain_id, _promo_file(_promotion("1", _promo_item(MILK, price="5.00"))))
    # The store's prices are not in: none of its promotions matches a product.
    unknown = _promo_file(_promotion("2", _promo_item("99999999", price="5.00")))
    with pytest.raises(ValueError, match="no promotion matched a known product"):
        _promos(factory, chain_id, unknown, NOW + timedelta(hours=6))
    # Rolled back: the promotions the store had are as they were.
    assert set(_active(factory, store_id, NOW + timedelta(hours=6))) == {"1"}
    assert [r["gov_promotion_id"] for r in _rows(engine, "SELECT * FROM promotions")] == ["1"]


@pytest.mark.usefixtures("products")
def test_a_promotion_gone_from_the_file_ends(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, store_id = store
    first = _promo_file(
        _promotion("1", _promo_item(MILK, price="5.00")),
        _promotion("2", _promo_item(BREAD, price="5.00")),
        _promotion("future", _promo_item(BREAD, price="4.00"), start="2026-11-20T00:00:00"),
    )
    _promos(factory, chain_id, first)
    later = NOW + timedelta(hours=6)
    second = _promo_file(
        _promotion("1", _promo_item(MILK, price="4.50"), _promo_item(BREAD, price="4.50"))
    )
    assert _promos(factory, chain_id, second, later) == 1

    ends = {
        r["gov_promotion_id"]: (r["starts_at"], r["ends_at"])
        for r in _rows(engine, "SELECT * FROM promotions")
    }
    assert ends["2"][1] == later
    # One that had not started ends as it starts: never in effect.
    assert ends["future"][1] == ends["future"][0]
    assert set(_active(factory, store_id, later)) == {"1"}
    one = _active(factory, store_id, later)["1"]
    assert one.bundle_price_agorot == 450
    assert set(one.product_ids) == {_product_id(engine, MILK), _product_id(engine, BREAD)}
    assert set(_active(factory, store_id, datetime(2026, 11, 21, tzinfo=UTC))) == {"1"}

    # It comes back with the next file that has it.
    _promos(factory, chain_id, first, later + timedelta(hours=6))
    assert set(_active(factory, store_id, later + timedelta(hours=6))) == {"1", "2"}


@pytest.mark.usefixtures("products")
def test_a_promotion_of_another_store_is_not_ended(
    engine: Engine, factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, store_id = store
    _, other = _store(factory, CODE, "102")
    _promos(factory, chain_id, _promo_file(_promotion("1", _promo_item(MILK, price="5.00"))))
    _promos(
        factory,
        chain_id,
        _promo_file(_promotion("1", _promo_item(MILK, price="6.00")), store="102"),
    )
    _promos(factory, chain_id, _promo_file(store="102"))
    assert set(_active(factory, store_id)) == {"1"}
    assert _active(factory, other) == {}


@pytest.mark.usefixtures("products")
def test_an_expired_promotion_is_not_active_later(
    factory: sessionmaker[Session], store: Any
) -> None:
    chain_id, store_id = store
    data = _promo_file(_promotion("1", _promo_item(MILK, price="5.00"), end="2026-11-04T00:00"))
    _promos(factory, chain_id, data)
    assert set(_active(factory, store_id)) == {"1"}
    assert _active(factory, store_id, datetime(2026, 11, 3, 22, 0, tzinfo=UTC)) == {}
    # Before it starts, neither.
    assert _active(factory, store_id, datetime(2026, 10, 31, 21, 0, tzinfo=UTC)) == {}


def test_active_promotions_of_no_store(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        assert pricing_service.active_promotions(session, [], NOW) == []


# --- A whole run ---


def _run(factory: sessionmaker[Session], adapter: FakeAdapter, **kwargs: Any) -> RunSummary:
    handlers = {
        **service.DEFAULT_HANDLERS,
        "price_full": prices.price_handler(lambda: NOW),
        "promo_full": prices.promo_handler(lambda: NOW),
    }
    summary = ingest_chain(factory, adapter, handlers=handlers, now=lambda: NOW, **kwargs)
    assert summary is not None
    return summary


def test_a_run_of_stores_prices_and_promotions(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    summary = _run(factory, FakeAdapter(_good_files()))
    assert summary.status == "succeeded"

    [store] = _rows(engine, "SELECT id FROM stores WHERE gov_store_code = '101'")
    store_id = store["id"]
    # The view was refreshed at the end of the run.
    assert _current(factory, store_id) == {
        MILK: (690, "unit"),
        BREAD: (950, "unit"),
        CHEESE: (6600, "kg"),
        "עגבניה בדויה": (790, "kg"),  # with an internal code: a proposed product
    }
    active = _active(factory, store_id)
    assert set(active) == {"1", "2"}  # 3 is a coupon
    assert (active["1"].kind, active["1"].min_qty, active["1"].bundle_price_agorot) == (
        "multi_buy",
        Decimal(2),
        1000,
    )
    assert active["1"].club_id is None
    assert (active["2"].kind, active["2"].bundle_price_agorot) == ("fixed_price", 5990)
    assert _club_name(engine, active["2"].club_id) == "מועדון רשת בדויה"
    [obs] = _rows(engine, "SELECT DISTINCT source_ref FROM price_observations")
    assert obs["source_ref"] == PRICE
    records = {r["file_name"]: r["records"] for r in _rows(engine, "SELECT * FROM ingestion_files")}
    assert (records[PRICE], records[PROMO]) == (4, 2)


def test_a_file_of_an_unknown_store_fails_alone(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    files = _good_files()
    unknown = f"PriceFull{CODE}-001-009-20261103-010000.gz"
    files[unknown] = gzip.compress(_price_file(_item(MILK, "1.00"), store="009"))
    summary = _run(factory, FakeAdapter(files))

    assert summary.status == "partial"
    rows = {r["file_name"]: r for r in _rows(engine, "SELECT * FROM ingestion_files")}
    assert rows[unknown]["status"] == "failed"
    assert rows[unknown]["error"] == "UnknownStoreError: unknown store 9"
    assert {rows[name]["status"] for name in rows if name != unknown} == {"succeeded"}
    # A partial run refreshes the view as well.
    [store] = _rows(engine, "SELECT id FROM stores WHERE gov_store_code = '101'")
    assert len(_current(factory, store["id"])) == 4

    # Once the store is in the Stores file, the same file is taken again.
    _store(factory, CODE, "9")
    again = _run(factory, FakeAdapter(files))
    assert (again.files_ingested, again.files_skipped) == (1, 3)


def test_a_run_that_ingests_nothing_does_not_refresh(
    factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    refresh = pricing_service.refresh_current_prices

    def counted(session: Session) -> None:
        calls.append(1)
        refresh(session)

    monkeypatch.setattr(service.pricing_service, "refresh_current_prices", counted)
    _run(factory, FakeAdapter(_good_files()))
    assert len(calls) == 1
    again = _run(factory, FakeAdapter(_good_files()))
    assert again.files_skipped == 3
    assert len(calls) == 1


def test_a_failed_refresh_leaves_the_run_as_it_is(
    engine: Engine, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_session: Session) -> None:
        raise RuntimeError("refresh broke")

    monkeypatch.setattr(service.pricing_service, "refresh_current_prices", broken)
    summary = _run(factory, FakeAdapter(_good_files()))
    assert summary.status == "succeeded"
    [run] = _rows(engine, "SELECT status, error FROM ingestion_runs")
    assert run == {"status": "succeeded", "error": None}


# --- Schema ---


def test_the_schema(engine: Engine) -> None:
    insp = inspect(engine)
    assert ["barcode"] in [u["column_names"] for u in insp.get_unique_constraints("products")]
    assert ["store_id", "gov_promotion_id"] in [
        u["column_names"] for u in insp.get_unique_constraints("promotions")
    ]
    assert insp.get_pk_constraint("promotion_products")["constrained_columns"] == [
        "promotion_id",
        "product_id",
    ]
    with engine.connect() as conn:
        indexes = dict(conn.execute(text("SELECT indexname, indexdef FROM pg_indexes")).all())
        kind = conn.execute(
            text("SELECT relkind FROM pg_class WHERE relname = 'current_prices'")
        ).scalar_one()
    assert "gin_trgm_ops" in indexes["ix_products_name_norm"]
    assert "observed_at DESC" in indexes["ix_price_observations_store_product_observed"]
    assert "UNIQUE" in indexes["ux_current_prices"]
    assert kind == "m"


def test_the_checks(engine: Engine, factory: sessionmaker[Session], store: Any) -> None:
    chain_id, store_id = store
    _prices(factory, chain_id, _price_file(_item(MILK, "1.00")))
    product_id = _product_id(engine, MILK)
    observation = text(
        "INSERT INTO price_observations (id, product_id, store_id, chain_id, source, price_type, "
        "unit_price_agorot, per, observed_at, status, created_at) VALUES "
        "(:id, :p, :s, :c, :source, :type, :price, :per, now(), :status, now())"
    )
    good = {"source": "official_file", "type": "regular", "price": 100, "per": "unit"}
    for bad in (
        {"source": "guess"},
        {"type": "sale"},
        {"price": 0},
        {"per": "box"},
        {"status": "maybe"},
    ):
        params = {"id": uuid.uuid4(), "p": product_id, "s": store_id, "c": chain_id}
        params |= {**good, "status": "valid", **bad}
        with pytest.raises(Exception, match="ck_price_observations_"), engine.begin() as conn:
            conn.execute(observation, params)
    with pytest.raises(Exception, match="ck_products_pack_unit"), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO products (id, name, name_norm, pack_unit, is_weighted, status, "
                "created_at) VALUES (:id, 'n', 'n', 'box', false, 'active', now())"
            ),
            {"id": uuid.uuid4()},
        )


def test_models_match_the_migrations(prices_url: str) -> None:
    command.check(alembic_config(prices_url))  # raises when autogenerate would find a change


def test_prices_migration_roundtrip_adds_no_data(db_url: str) -> None:
    url = create_database(db_url, "cw_prices_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    new = {"products", "price_observations", "promotions", "promotion_products"}
    try:
        command.upgrade(cfg, "0008")
        assert not new & set(inspect(eng).get_table_names())
        command.upgrade(cfg, "0009")
        with eng.connect() as conn:
            for table in (*new, "current_prices"):
                assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0  # noqa: S608
        command.downgrade(cfg, "0008")
        tables = set(inspect(eng).get_table_names())
        assert not new & tables
        assert "current_prices" not in inspect(eng).get_materialized_view_names()
        assert {"stores", "chains", "ingestion_files"} <= tables
    finally:
        eng.dispose()
