"""Stores files (Story 3.3): parse_stores, the geocoding query and settlement names. No DB."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.modules.catalog import service as catalog_service
from app.modules.catalog.service import StoreRecord, StoreState
from app.modules.ingestion.decode import decode_xml
from app.modules.ingestion.stores import needs_geocode, parse_stores
from scripts import store_locations

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingestion"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def _record(**fields: object) -> StoreRecord:
    values: dict[str, object] = {
        "gov_store_code": "1",
        "sub_chain_code": "1",
        "name": "סניף בדוי",
        "address": "רחוב הדמיון 1",
        "city_code": "3000",
        "zip_code": None,
        "store_type": 1,
    }
    values.update(fields)
    return StoreRecord(**values)  # type: ignore[arg-type]


def test_the_fixture_is_parsed() -> None:
    root = decode_xml((FIXTURES / "stores.utf16.xml").read_bytes())
    records, skipped = parse_stores(root)
    assert skipped == 0
    assert [(r.gov_store_code, r.sub_chain_code, r.name) for r in records] == [
        ("101", "1", "סניף הדקל"),
        ("102", "1", "סניף התמר"),
    ]
    assert records[0].address == "רחוב הדמיון 1"
    assert (records[0].city_code, records[0].zip_code, records[0].store_type) == (
        "3000",
        "9100001",
        None,
    )


def test_upper_case_utf16_tags_and_a_namespace() -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<asx:abap xmlns:asx="http://www.sap.com/abapxml"><asx:values><ROOT><SUBCHAINS>'
        "<SUBCHAIN><SUBCHAINID>7</SUBCHAINID><STORES>"
        "<STORE><STOREID>001</STOREID><STORETYPE>1</STORETYPE><STORENAME>סניף  בדוי</STORENAME>"
        "<ADDRESS> רחוב   השקר 3 </ADDRESS><CITY>3000</CITY><ZIPCODE></ZIPCODE></STORE>"
        "<STORE><STOREID>000</STOREID><STORETYPE>2</STORETYPE><STORENAME>אתר</STORENAME></STORE>"
        "</STORES></SUBCHAIN></SUBCHAINS></ROOT></asx:values></asx:abap>"
    )
    records, skipped = parse_stores(decode_xml(xml.encode("utf-16")))
    assert skipped == 0
    first, online = records
    assert (first.gov_store_code, first.sub_chain_code, first.name) == ("1", "7", "סניף בדוי")
    assert first.address == "רחוב השקר 3"
    assert first.zip_code is None
    assert not first.online
    assert (online.gov_store_code, online.store_type, online.online) == ("0", 2, True)
    assert online.address == ""
    assert online.city_code is None


@pytest.mark.parametrize(
    "store",
    [
        "<Store><StoreName>בלי קוד</StoreName></Store>",
        "<Store><StoreId>12a</StoreId><StoreName>קוד לא ספרתי</StoreName></Store>",
        "<Store><StoreId>٣</StoreId><StoreName>ספרה לא ASCII</StoreName></Store>",
        "<Store><StoreId>5</StoreId></Store>",
        "<Store><StoreId>5</StoreId><StoreName>  </StoreName></Store>",
    ],
)
def test_a_broken_store_is_skipped(store: str) -> None:
    good = "<Store><StoreId>9</StoreId><StoreName>טוב</StoreName></Store>"
    xml = f"<Root><Stores>{store}{good}</Stores></Root>"
    records, skipped = parse_stores(decode_xml(xml.encode()))
    assert skipped == 1
    assert [r.gov_store_code for r in records] == ["9"]
    assert records[0].sub_chain_code is None


def test_jerusalem_is_found_by_its_code() -> None:
    assert catalog_service.settlement_name("3000") == "ירושלים"
    assert catalog_service.settlement_name(" 03000 ") == "ירושלים"
    assert catalog_service.settlement_name("99999") is None
    assert catalog_service.settlement_name("") is None
    assert catalog_service.settlement_name("abc") is None


def test_every_settlement_is_loaded() -> None:
    found = sum(catalog_service.settlement_name(str(code)) is not None for code in range(100_000))
    assert found >= 1300
    assert catalog_service.settlement_name("4000") == "חיפה"
    assert catalog_service.settlement_name("5000") == "תל אביב - יפו"
    assert catalog_service.settlement_name("70") == "אשדוד"


@pytest.mark.parametrize(("value", "expected"), [("32767", 32767), ("32768", None), ("x", None)])
def test_a_store_type_out_of_range_is_none(value: str, expected: int | None) -> None:
    xml = (
        "<Root><Store><StoreId>1</StoreId><StoreName>סניף</StoreName>"
        f"<StoreType>{value}</StoreType></Store></Root>"
    )
    [record], _skipped = parse_stores(decode_xml(xml.encode()))
    assert record.store_type == expected


@pytest.mark.parametrize(
    ("address", "city", "query"),
    [
        ("רחוב הדמיון 1", "3000", "רחוב הדמיון 1, ירושלים"),
        ("רחוב הדמיון 1", "99999", "רחוב הדמיון 1"),
        ("רחוב הדמיון 1", None, "רחוב הדמיון 1"),
        ("רחוב הדמיון 1", "", "רחוב הדמיון 1"),
        ("רחוב הדמיון 1", "בית  שמש", "רחוב הדמיון 1, בית שמש"),
        ("  רחוב   הדמיון\t1 ", "3000", "רחוב הדמיון 1, ירושלים"),
        ("", "3000", None),
    ],
)
def test_the_geocoding_query(address: str, city: str | None, query: str | None) -> None:
    assert catalog_service.store_geocode_query(_record(address=address, city_code=city)) == query


def test_the_query_is_nfc() -> None:
    not_nfc = "רחוב שׁ 1"  # a presentation form, which NFC decomposes
    query = catalog_service.store_geocode_query(_record(address=not_nfc, city_code=None))
    assert query == "רחוב שׁ 1"


def _state(**fields: object) -> StoreState:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "status": "needs_location",
        "has_location": False,
        "location_source": None,
        "geocoded_query": None,
        "geocode_attempted_at": None,
    }
    values.update(fields)
    return StoreState(**values)  # type: ignore[arg-type]


Q = "רחוב הדמיון 1, ירושלים"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state(), True),
        (
            _state(
                status="active", has_location=True, location_source="geocoded", geocoded_query=Q
            ),
            False,
        ),
        (
            _state(
                status="active", has_location=True, location_source="geocoded", geocoded_query="x"
            ),
            True,
        ),
        (
            _state(
                status="active", has_location=True, location_source="manual", geocoded_query="x"
            ),
            False,
        ),
        (_state(status="active", has_location=True, location_source="manual"), False),
        (_state(geocoded_query=Q, geocode_attempted_at=NOW - timedelta(hours=1)), False),
        (_state(geocoded_query=Q, geocode_attempted_at=NOW - timedelta(hours=25)), True),
        (_state(geocoded_query="x", geocode_attempted_at=NOW - timedelta(hours=1)), True),
        # An old location, and the new address failed: retried a day later.
        (
            _state(
                status="active",
                has_location=True,
                location_source="geocoded",
                geocoded_query=Q,
                geocode_attempted_at=NOW - timedelta(hours=1),
            ),
            False,
        ),
        (
            _state(
                status="active",
                has_location=True,
                location_source="geocoded",
                geocoded_query=Q,
                geocode_attempted_at=NOW - timedelta(hours=25),
            ),
            True,
        ),
    ],
)
def test_who_is_geocoded(state: StoreState, expected: bool) -> None:
    assert needs_geocode(state, Q, NOW) is expected


def test_the_cli_refuses_to_run_with_no_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none")
    get_settings.cache_clear()
    try:
        assert store_locations.main(["list"]) == 1
    finally:
        get_settings.cache_clear()
    assert "no database" in capsys.readouterr().err
