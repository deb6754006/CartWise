"""Parsing PriceFull and PromoFull files (Story 3.4): no database. The fixtures are fictional."""

import gzip
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from xml.etree.ElementTree import Element

import pytest

from app.modules.ingestion.decode import decode_xml
from app.modules.ingestion.prices import (
    PromoItem,
    Reward,
    UnknownStoreError,
    club_is_everyone,
    local_to_utc,
    pack_unit,
    parse_price_file,
    parse_promo_file,
    promotion_reward,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingestion"


def _root(xml: str) -> Element:
    return decode_xml(xml.encode())


def _price_file(*items: str, store: str = "101") -> str:
    body = "".join(items)
    return f"<Root><ChainId>1</ChainId><StoreId>{store}</StoreId><Items>{body}</Items></Root>"


def _item(
    code: str = "1000000000001",
    price: str = "13.90",
    item_type: str = "1",
    name: str = "מוצר בדוי",
    extra: str = "",
) -> str:
    return (
        f"<Item><ItemCode>{code}</ItemCode><ItemType>{item_type}</ItemType>"
        f"<ItemName>{name}</ItemName><ItemPrice>{price}</ItemPrice>{extra}</Item>"
    )


def test_the_price_fixture() -> None:
    parsed = parse_price_file(decode_xml(gzip.compress((FIXTURES / "price_full.xml").read_bytes())))
    assert parsed.store_code == "101"
    assert [(i.barcode, i.price_agorot, i.per) for i in parsed.items] == [
        ("1000000000001", 690, "unit"),
        ("1000000000002", 950, "unit"),
        ("1000000000003", 6600, "kg"),
    ]
    milk, bread, cheese = parsed.items
    assert (milk.pack_size, milk.pack_unit, milk.is_weighted) == (Decimal("1.00"), "l", False)
    assert (bread.pack_size, bread.pack_unit) == (Decimal("750.00"), "g")
    assert (cheese.pack_unit, cheese.is_weighted) == ("kg", True)
    # 08:00 in Israel, winter time (UTC+2).
    assert milk.observed_at == datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    assert parsed.skipped == {"no_barcode": 1}


@pytest.mark.parametrize(
    ("price", "agorot"),
    [("13.90", 1390), ("13.9", 1390), ("13.905", 1391), ("0.01", 1), ("13", 1300)],
)
def test_prices_in_agorot(price: str, agorot: int) -> None:
    [item] = parse_price_file(_root(_price_file(_item(price=price)))).items
    assert item.price_agorot == agorot


@pytest.mark.parametrize(
    "price", ["abc", "0", "-1", "", "NaN", "0.004", "99999999999", "1e30", "1E+999999"]
)
def test_a_bad_price_is_skipped(price: str) -> None:
    parsed = parse_price_file(_root(_price_file(_item(price=price), _item(code="10000002"))))
    assert [i.barcode for i in parsed.items] == ["10000002"]
    assert parsed.skipped == {"bad_price": 1}


@pytest.mark.parametrize(
    ("code", "item_type"),
    [
        ("7001", "0"),
        ("1000000000001", "0"),
        ("1234567", "1"),
        ("123456789012345", "1"),
        ("12345678A", "1"),
        ("1000000000001", ""),
        # A placeholder, not a barcode.
        ("00000000", "1"),
        ("0000000000000", "1"),
    ],
)
def test_an_item_with_no_barcode_is_skipped(code: str, item_type: str) -> None:
    parsed = parse_price_file(_root(_price_file(_item(code=code, item_type=item_type))))
    assert parsed.items == []
    assert parsed.skipped == {"no_barcode": 1}


def test_a_barcode_is_kept_as_it_is() -> None:
    [item] = parse_price_file(_root(_price_file(_item(code="00012345")))).items
    assert item.barcode == "00012345"


def test_the_first_item_of_a_barcode_wins() -> None:
    parsed = parse_price_file(_root(_price_file(_item(price="5.00"), _item(price="6.00"))))
    assert [i.price_agorot for i in parsed.items] == [500]
    assert parsed.skipped == {"duplicate": 1}


def test_an_item_with_no_name_is_skipped() -> None:
    parsed = parse_price_file(_root(_price_file(_item(name=""))))
    assert parsed.items == []
    assert parsed.skipped == {"no_name": 1}


def test_a_weighted_item_is_per_kg() -> None:
    extra = "<bIsWeighted>1</bIsWeighted><UnitQty>קילוגרם</UnitQty><Quantity>1</Quantity>"
    [item] = parse_price_file(_root(_price_file(_item(price="66.00", extra=extra)))).items
    assert (item.per, item.price_agorot, item.is_weighted) == ("kg", 6600, True)


def test_the_store_code_drops_leading_zeros() -> None:
    assert parse_price_file(_root(_price_file(store="005"))).store_code == "5"
    assert parse_price_file(_root(_price_file(store="000"))).store_code == "0"


@pytest.mark.parametrize("store", ["", "abc"])
def test_a_file_with_no_store_fails(store: str) -> None:
    with pytest.raises(UnknownStoreError, match="unknown store"):
        parse_price_file(_root(_price_file(store=store)))


def test_tags_in_any_case_and_namespace() -> None:
    xml = (
        '<x:ROOT xmlns:x="urn:x"><x:STOREID>7</x:STOREID><ITEMS><ITEM><ITEMCODE>10000001'
        "</ITEMCODE><ITEMTYPE>1</ITEMTYPE><ITEMNAME>בדוי</ITEMNAME><ITEMPRICE>1.50</ITEMPRICE>"
        "</ITEM></ITEMS></x:ROOT>"
    )
    parsed = parse_price_file(_root(xml))
    assert parsed.store_code == "7"
    assert [(i.barcode, i.price_agorot) for i in parsed.items] == [("10000001", 150)]


@pytest.mark.parametrize(
    ("unit_qty", "unit"),
    [
        ("גרם", "g"),
        ("קילוגרם", "kg"),
        ('ק"ג', "kg"),
        ("ק״ג", "kg"),
        ("מיליליטר", "ml"),
        ('מ"ל', "ml"),
        ("ליטר", "l"),
        ("יחידה", "unit"),
        ("יח'", "unit"),
        (" ליטר ", "l"),
        ("מטר", None),
        ("", None),
        ("Unknown", None),
    ],
)
def test_pack_units(unit_qty: str, unit: str | None) -> None:
    assert pack_unit(unit_qty) == unit


def test_an_unknown_unit_has_no_pack_size() -> None:
    extra = "<UnitQty>מטר</UnitQty><Quantity>3</Quantity>"
    [item] = parse_price_file(_root(_price_file(_item(extra=extra)))).items
    assert (item.pack_size, item.pack_unit) == (None, None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Winter time (UTC+2) and summer time (UTC+3).
        ("2026-11-01T00:00:00.000", datetime(2026, 10, 31, 22, 0, tzinfo=UTC)),
        ("2026-07-01 12:00:00", datetime(2026, 7, 1, 9, 0, tzinfo=UTC)),
        ("2026-07-01 12:00", datetime(2026, 7, 1, 9, 0, tzinfo=UTC)),
        ("2026/07/01 12:00:00", datetime(2026, 7, 1, 9, 0, tzinfo=UTC)),
        ("2026-07-01T12:00:00+00:00", datetime(2026, 7, 1, 12, 0, tzinfo=UTC)),
        ("", None),
        ("yesterday", None),
        ("2026-13-01 00:00", None),
        # Too close to datetime.min or max to move to UTC.
        ("0001-01-01 00:00:00", None),
        ("9999-12-31T23:59:59-05:00", None),
    ],
)
def test_local_to_utc(text: str, expected: datetime | None) -> None:
    assert local_to_utc(text) == expected


def test_a_bad_update_time_is_none() -> None:
    extra = "<PriceUpdateTime>never</PriceUpdateTime>"
    [item] = parse_price_file(_root(_price_file(_item(extra=extra)))).items
    assert item.observed_at is None


@pytest.mark.parametrize(
    ("club", "everyone"),
    [
        ("0", True),
        (" 0 ", True),
        ("0 - כלל הלקוחות", True),
        ("0 - כלל הלקוחות ", True),
        ("", False),
        ("2 - מועדון בדוי", False),
        ("(0=מועדון קרפור אשראי|0=מועדון אפליקציה)", False),
        ("(2=מועדון קרפור אשראי|2=מועדון אפליקציה)", False),
        ("0|1", False),
        ("0&1", False),
        ("00", False),
        ("1", False),
    ],
)
def test_club_is_everyone(club: str, everyone: bool) -> None:
    assert club_is_everyone(club) is everyone


def test_the_promo_fixture() -> None:
    parsed = parse_promo_file(decode_xml((FIXTURES / "promo_full.xml").read_bytes()))
    assert parsed.store_code == "101"
    assert [p.gov_promotion_id for p in parsed.promotions] == ["1", "2", "3"]
    two_for, club, coupon = parsed.promotions
    assert two_for.club == "0 - כלל הלקוחות"
    assert two_for.starts_at == datetime(2026, 10, 31, 22, 0, tzinfo=UTC)
    assert two_for.ends_at == datetime(2099, 12, 31, 21, 59, tzinfo=UTC)
    assert [
        (i.barcode, i.reward_type, i.min_qty, i.discounted_price_agorot) for i in two_for.items
    ] == [
        ("1000000000001", "10", Decimal(2), 1000),
        ("1000000000002", "10", Decimal(2), 1000),
    ]
    assert not two_for.is_coupon
    assert club.club == "(2=מועדון בדוי|2=מועדון אפליקציה)"
    assert club.items[0].min_qty == Decimal("0.010")
    assert coupon.is_coupon


def _promo(body: str, fields: str = "") -> str:
    return (
        "<Root><StoreId>101</StoreId><Promotions><Promotion><PromotionId>9</PromotionId>"
        f"{fields}<Groups><Group><PromotionItems>{body}</PromotionItems></Group></Groups>"
        "</Promotion></Promotions></Root>"
    )


def test_a_promotion_with_the_reward_on_the_promotion() -> None:
    fields = (
        "<PromotionStartDate>2026-11-01</PromotionStartDate>"
        "<PromotionStartHour>08:00:00</PromotionStartHour><RewardType>10</RewardType>"
        "<MinQty>3</MinQty><DiscountedPrice>25</DiscountedPrice>"
    )
    item = "<PromotionItem><ItemCode>10000001</ItemCode><ItemType>1</ItemType></PromotionItem>"
    [promo] = parse_promo_file(_root(_promo(item, fields))).promotions
    assert promo.starts_at == datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    assert promo.ends_at is None
    assert promo.items == (PromoItem("10000001", "10", Decimal(3), None, 2500),)


def test_the_first_promotion_of_an_id_wins() -> None:
    xml = (
        "<Root><StoreId>1</StoreId><Promotions>"
        "<Promotion><PromotionId>9</PromotionId><PromotionDescription>א</PromotionDescription>"
        "</Promotion><Promotion><PromotionId>9</PromotionId></Promotion>"
        "<Promotion><PromotionId></PromotionId></Promotion></Promotions></Root>"
    )
    parsed = parse_promo_file(_root(xml))
    assert [p.description for p in parsed.promotions] == ["א"]
    assert parsed.skipped == {"duplicate": 1, "no_id": 1}


def _reward_item(
    reward: str, min_qty: str | None = "1", rate: str | None = None, price: int | None = None
) -> PromoItem:
    return PromoItem(
        barcode="10000001",
        reward_type=reward,
        min_qty=Decimal(min_qty) if min_qty is not None else None,
        discount_rate=Decimal(rate) if rate is not None else None,
        discounted_price_agorot=price,
    )


@pytest.mark.parametrize(
    ("item", "reward"),
    [
        # 2 for 20.
        (_reward_item("10", "2", price=2000), Reward("multi_buy", Decimal(2), 2000, None)),
        (_reward_item("1", "3", price=2500), Reward("multi_buy", Decimal(3), 2500, None)),
        (_reward_item("10", None, price=2000), Reward("multi_buy", Decimal(1), 2000, None)),
        (_reward_item("10", "2"), None),
        (_reward_item("2", rate="5"), Reward("percent", Decimal(1), None, Decimal(5))),
        # The rate applies: each item's own DiscountedPrice is not kept.
        (_reward_item("2", rate="5", price=950), Reward("percent", Decimal(1), None, Decimal(5))),
        # A percent with MinQty > 1 is a percent, not a multi-buy.
        (
            _reward_item("2", "3", rate="10", price=2500),
            Reward("percent", Decimal(1), None, Decimal(10)),
        ),
        (_reward_item("2", rate="0", price=950), Reward("fixed_price", Decimal(1), 950, None)),
        (_reward_item("2", rate="150"), None),
        (_reward_item("3", price=2490), Reward("fixed_price", Decimal(1), 2490, None)),
        (_reward_item("3", "0.010", price=5990), Reward("fixed_price", Decimal(1), 5990, None)),
        (_reward_item("1", price=1000), Reward("fixed_price", Decimal(1), 1000, None)),
        (_reward_item("3"), None),
        (_reward_item("1"), None),
    ],
)
def test_promotion_reward(item: PromoItem, reward: Reward | None) -> None:
    assert promotion_reward(item) == reward
