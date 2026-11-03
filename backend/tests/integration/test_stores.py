"""Stores and their locations (Story 3.3), against Postgres, with a fake geocoder: no network."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import make_engine
from app.core.errors import AppError
from app.modules.catalog import service as catalog_service
from app.modules.geo.service import GeoPoint, geocoding_unavailable
from app.modules.ingestion import stores
from app.modules.ingestion.decode import decode_xml
from app.modules.ingestion.service import handlers_with_geocoder, ingest_chain
from scripts import store_locations
from tests.integration.pg import alembic_config, create_database
from tests.integration.test_ingestion import CODE, STORES, FakeAdapter

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
ADDRESS = "רחוב הדמיון 1"
JERUSALEM = GeoPoint(lat=31.7767, lng=35.2345)
ELSEWHERE = GeoPoint(lat=32.0853, lng=34.7818)


class FakeGeocoder:
    def __init__(self, point: GeoPoint | None = JERUSALEM) -> None:
        self.point = point
        self.fail = False
        self.calls: list[str] = []

    def locate(self, address: str) -> GeoPoint | None:
        self.calls.append(address)
        if self.fail:
            raise geocoding_unavailable()
        return self.point


@pytest.fixture(scope="module")
def stores_url(db_url: str) -> str:
    """A database of its own: these tests truncate and count rows."""
    url = create_database(db_url, "cw_stores")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(stores_url: str) -> Iterator[Engine]:
    eng = make_engine(stores_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE promotion_products, promotions, price_observations, products, "
                "ingestion_files, ingestion_runs, stores, user_clubs, clubs, chains"
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def chain_id(factory: sessionmaker[Session]) -> uuid.UUID:
    with factory() as session:
        chain = catalog_service.ensure_chain(session, CODE, "רשת בדויה")
        session.commit()
    return chain


def _store(
    store_id: str = "001",
    name: str = "סניף הדקל",
    address: str = ADDRESS,
    city: str = "3000",
    store_type: str = "1",
) -> str:
    return (
        f"<Store><StoreId>{store_id}</StoreId><StoreType>{store_type}</StoreType>"
        f"<StoreName>{name}</StoreName><Address>{address}</Address><City>{city}</City>"
        "<ZipCode>9100001</ZipCode></Store>"
    )


def _file(*stores_xml: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-16"?><Root><ChainId>7290000000001</ChainId>'
        "<SubChains><SubChain><SubChainId>1</SubChainId><Stores>"
        + "".join(stores_xml)
        + "</Stores></SubChain></SubChains></Root>"
    ).encode("utf-16")


def _handle(
    factory: sessionmaker[Session],
    chain_id: uuid.UUID,
    geocoder: FakeGeocoder,
    data: bytes,
    now: datetime = NOW,
    max_geocodes: int = stores.MAX_GEOCODES_PER_FILE,
) -> int:
    handler = stores.stores_handler(geocoder, now=lambda: now, max_geocodes=max_geocodes)
    with factory() as session:
        count = handler(session, chain_id, decode_xml(data))
        session.commit()
    return count


def _rows(engine: Engine) -> list[dict[str, Any]]:
    sql = (
        "SELECT *, ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng "
        "FROM stores ORDER BY length(gov_store_code), gov_store_code"
    )
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql))]


def _comparable(factory: sessionmaker[Session]) -> list[uuid.UUID]:
    with factory() as session:
        return catalog_service.comparable_store_ids(session)


def _needing(factory: sessionmaker[Session]) -> list[uuid.UUID]:
    with factory() as session:
        return [store.id for store in catalog_service.stores_needing_location(session)]


def test_a_new_store_is_located(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID
) -> None:
    geocoder = FakeGeocoder()
    assert _handle(factory, chain_id, geocoder, _file(_store())) == 1

    assert geocoder.calls == [f"{ADDRESS}, ירושלים"]
    [row] = _rows(engine)
    assert (row["chain_id"], row["gov_store_code"], row["sub_chain_code"]) == (chain_id, "1", "1")
    assert (row["name"], row["name_norm"], row["address"]) == ("סניף הדקל", "סניף הדקל", ADDRESS)
    assert (row["city_code"], row["zip_code"], row["store_type"]) == ("3000", "9100001", 1)
    assert row["status"] == "active"
    assert (row["lat"], row["lng"]) == pytest.approx((JERUSALEM.lat, JERUSALEM.lng))
    assert row["location_source"] == "geocoded"
    assert row["geocoded_query"] == f"{ADDRESS}, ירושלים"
    assert row["geocode_attempted_at"] is None
    assert row["last_seen_at"] == row["created_at"] == row["updated_at"] == NOW
    assert _comparable(factory) == [row["id"]]
    assert _needing(factory) == []


@pytest.mark.parametrize("fail", [False, True])
def test_a_new_store_with_no_location(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID, fail: bool
) -> None:
    geocoder = FakeGeocoder(point=None)
    geocoder.fail = fail
    _handle(factory, chain_id, geocoder, _file(_store()))

    [row] = _rows(engine)
    assert row["status"] == "needs_location"
    assert row["location"] is None
    assert row["geocode_attempted_at"] == NOW
    assert _comparable(factory) == []
    with factory() as session:
        [ref] = catalog_service.stores_needing_location(session)
    assert (ref.id, ref.chain_id, ref.chain_name) == (row["id"], chain_id, "רשת בדויה")
    assert (ref.gov_store_code, ref.name, ref.address, ref.city_code) == (
        "1",
        "סניף הדקל",
        ADDRESS,
        "3000",
    )


def test_an_unavailable_geocoder_does_not_fail_the_file(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    geocoder = FakeGeocoder()
    geocoder.fail = True
    adapter = FakeAdapter({STORES: _file(_store(), _store("002"))})
    summary = ingest_chain(factory, adapter, handlers_with_geocoder(geocoder), now=lambda: NOW)

    assert summary is not None
    assert (summary.status, summary.files_ingested, summary.records) == ("succeeded", 1, 2)
    assert len(geocoder.calls) == 1
    assert [row["status"] for row in _rows(engine)] == ["needs_location", "needs_location"]


def test_an_unavailable_geocoder_stops_the_requests_for_the_file(
    engine: Engine,
    factory: sessionmaker[Session],
    chain_id: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    geocoder = FakeGeocoder()
    geocoder.fail = True
    data = _file(*(_store(f"{n:03}", address=f"רחוב {n}") for n in range(1, 4)))
    with caplog.at_level("INFO", logger="app.ingestion"):
        assert _handle(factory, chain_id, geocoder, data) == 3

    # The store that got the 503 failed; the others were not tried, and wait for the next run.
    assert geocoder.calls == ["רחוב 1, ירושלים"]
    rows = _rows(engine)
    assert [row["status"] for row in rows] == ["needs_location"] * 3
    assert [row["geocode_attempted_at"] for row in rows] == [NOW, None, None]
    [record] = [r for r in caplog.records if r.getMessage() == "ingestion_stores"]
    assert record.levelname == "WARNING"
    assert (record.geocode_unavailable, record.geocode_deferred) == (1, 2)  # type: ignore[attr-defined]

    geocoder.fail = False
    _handle(factory, chain_id, geocoder, data)
    assert geocoder.calls[1:] == ["רחוב 2, ירושלים", "רחוב 3, ירושלים"]


def test_another_geocoder_error_fails_the_file(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    class BrokenGeocoder(FakeGeocoder):
        def locate(self, address: str) -> GeoPoint | None:
            raise AppError("bad_request", "בקשה שגויה", status=400)

    adapter = FakeAdapter({STORES: _file(_store())})
    summary = ingest_chain(
        factory, adapter, handlers_with_geocoder(BrokenGeocoder()), now=lambda: NOW
    )
    assert summary is not None
    assert (summary.status, summary.files_failed) == ("failed", 1)
    assert _rows(engine) == []  # rolled back with the file


def test_a_store_that_goes_online_and_back(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID
) -> None:
    geocoder = FakeGeocoder()
    _handle(factory, chain_id, geocoder, _file(_store()))
    _handle(factory, chain_id, geocoder, _file(_store(store_type="2")))
    [row] = _rows(engine)
    assert (row["status"], row["store_type"]) == ("online", 2)
    assert _comparable(factory) == []

    _handle(factory, chain_id, geocoder, _file(_store()))
    [row] = _rows(engine)
    assert row["status"] == "active"  # it still has its location
    assert _comparable(factory) == [row["id"]]
    assert len(geocoder.calls) == 1


def test_the_same_address_again_is_not_geocoded(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID
) -> None:
    geocoder = FakeGeocoder()
    _handle(factory, chain_id, geocoder, _file(_store()))
    later = NOW + timedelta(hours=6)
    _handle(factory, chain_id, geocoder, _file(_store(name="סניף  הדקל החדש")), now=later)

    assert len(geocoder.calls) == 1
    [row] = _rows(engine)
    assert (row["name"], row["status"]) == ("סניף הדקל החדש", "active")
    assert (row["last_seen_at"], row["updated_at"], row["created_at"]) == (later, later, NOW)


def test_a_changed_address_is_geocoded_again(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID
) -> None:
    geocoder = FakeGeocoder()
    _handle(factory, chain_id, geocoder, _file(_store()))
    geocoder.point = ELSEWHERE
    _handle(factory, chain_id, geocoder, _file(_store(address="שדרות הבדיה 22")))

    assert geocoder.calls == [f"{ADDRESS}, ירושלים", "שדרות הבדיה 22, ירושלים"]
    [row] = _rows(engine)
    assert row["address"] == "שדרות הבדיה 22"
    assert (row["lat"], row["lng"]) == pytest.approx((ELSEWHERE.lat, ELSEWHERE.lng))
    assert row["geocoded_query"] == "שדרות הבדיה 22, ירושלים"


def test_a_failed_new_address_keeps_the_old_location(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID
) -> None:
    geocoder = FakeGeocoder()
    _handle(factory, chain_id, geocoder, _file(_store()))
    geocoder.point = None
    _handle(factory, chain_id, geocoder, _file(_store(address="שדרות הבדיה 22")))

    [row] = _rows(engine)
    assert row["status"] == "active"
    assert (row["lat"], row["lng"]) == pytest.approx((JERUSALEM.lat, JERUSALEM.lng))
    assert row["geocode_attempted_at"] == NOW
    assert _comparable(factory) == [row["id"]]
    # Not tried again within a day, and tried again after one.
    _handle(factory, chain_id, geocoder, _file(_store(address="שדרות הבדיה 22")))
    assert len(geocoder.calls) == 2
    geocoder.point = ELSEWHERE
    later = NOW + timedelta(hours=25)
    _handle(factory, chain_id, geocoder, _file(_store(address="שדרות הבדיה 22")), now=later)
    assert len(geocoder.calls) == 3
    [row] = _rows(engine)
    assert (row["lat"], row["lng"]) == pytest.approx((ELSEWHERE.lat, ELSEWHERE.lng))
    assert row["geocode_attempted_at"] is None


def test_a_manual_location_is_kept(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID
) -> None:
    geocoder = FakeGeocoder(point=None)
    _handle(factory, chain_id, geocoder, _file(_store()))
    [row] = _rows(engine)
    with factory() as session:
        catalog_service.set_store_location_manual(session, row["id"], 31.77, 35.21)
        session.commit()
    geocoder.point = ELSEWHERE
    later = NOW + timedelta(days=3)
    _handle(factory, chain_id, geocoder, _file(_store(address="שדרות הבדיה 22")), now=later)

    assert len(geocoder.calls) == 1
    [row] = _rows(engine)
    assert (row["location_source"], row["status"]) == ("manual", "active")
    assert (row["lat"], row["lng"]) == pytest.approx((31.77, 35.21))
    assert row["address"] == "שדרות הבדיה 22"


@pytest.mark.parametrize(("hours", "calls"), [(1, 1), (25, 2)])
def test_a_recent_failure_is_not_retried(
    engine: Engine,
    factory: sessionmaker[Session],
    chain_id: uuid.UUID,
    hours: int,
    calls: int,
) -> None:
    geocoder = FakeGeocoder(point=None)
    _handle(factory, chain_id, geocoder, _file(_store()))
    _handle(factory, chain_id, geocoder, _file(_store()), now=NOW + timedelta(hours=hours))
    assert len(geocoder.calls) == calls
    [row] = _rows(engine)
    assert row["status"] == "needs_location"


def test_an_online_store(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID
) -> None:
    geocoder = FakeGeocoder()
    _handle(factory, chain_id, geocoder, _file(_store("090", store_type="2")))

    assert geocoder.calls == []
    [row] = _rows(engine)
    assert (row["gov_store_code"], row["status"], row["store_type"]) == ("90", "online", 2)
    assert row["location"] is None
    assert _comparable(factory) == []
    assert _needing(factory) == []


@pytest.mark.parametrize("city", ["99999", ""])
def test_an_unknown_settlement_is_left_out_of_the_query(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID, city: str
) -> None:
    geocoder = FakeGeocoder()
    _handle(factory, chain_id, geocoder, _file(_store(city=city)))
    assert geocoder.calls == [ADDRESS]
    [row] = _rows(engine)
    assert row["city_code"] == (city or None)


def test_a_broken_store_is_skipped(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID
) -> None:
    broken = (
        "<Store><StoreName>בלי קוד</StoreName></Store>"
        "<Store><StoreId>x1</StoreId><StoreName>קוד לא ספרתי</StoreName></Store>"
    )
    count = _handle(factory, chain_id, FakeGeocoder(), _file(_store(), broken, _store("002")))
    assert count == 2
    assert [row["gov_store_code"] for row in _rows(engine)] == ["1", "2"]


def test_the_geocoding_cap(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID
) -> None:
    geocoder = FakeGeocoder()
    data = _file(*(_store(f"{n:03}", address=f"רחוב {n}") for n in range(1, 5)))
    _handle(factory, chain_id, geocoder, data, max_geocodes=3)

    assert len(geocoder.calls) == 3
    rows = _rows(engine)
    assert [row["status"] for row in rows] == ["active", "active", "active", "needs_location"]
    assert rows[-1]["geocode_attempted_at"] is None
    # The one left over is geocoded in the next run.
    _handle(factory, chain_id, geocoder, data, max_geocodes=3)
    assert geocoder.calls[3:] == ["רחוב 4, ירושלים"]
    assert _rows(engine)[-1]["status"] == "active"


def test_upper_case_tags_through_a_run(engine: Engine, factory: sessionmaker[Session]) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?><ROOT><SUBCHAINS><SUBCHAIN>'
        "<SUBCHAINID>3</SUBCHAINID><STORES><STORE><STOREID>007</STOREID>"
        "<STORETYPE>1</STORETYPE><STORENAME>סניף התמר</STORENAME>"
        f"<ADDRESS>{ADDRESS}</ADDRESS><CITY>3000</CITY><ZIPCODE></ZIPCODE></STORE>"
        "</STORES></SUBCHAIN></SUBCHAINS></ROOT>"
    ).encode("utf-16")
    geocoder = FakeGeocoder()
    summary = ingest_chain(
        factory, FakeAdapter({STORES: xml}), handlers_with_geocoder(geocoder), now=lambda: NOW
    )
    assert summary is not None
    assert (summary.status, summary.records) == ("succeeded", 1)
    [row] = _rows(engine)
    assert (row["gov_store_code"], row["sub_chain_code"], row["status"]) == ("7", "3", "active")
    assert row["zip_code"] is None


def test_set_a_location_with_the_cli(
    engine: Engine,
    factory: sessionmaker[Session],
    chain_id: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _handle(factory, chain_id, FakeGeocoder(point=None), _file(_store()))
    [row] = _rows(engine)

    assert store_locations.run(["list"], factory) == 0
    listed = capsys.readouterr().out.strip().split("\t")
    assert listed == [str(row["id"]), "רשת בדויה", "1", "סניף הדקל", ADDRESS, "3000"]

    for bad in (["91", "35.21"], ["31.77", "181"], ["nan", "35.21"], ["x", "35.21"]):
        assert store_locations.run(["set", str(row["id"]), *bad], factory) == 1
    assert store_locations.run(["set", str(uuid.uuid4()), "31.77", "35.21"], factory) == 1
    assert store_locations.run(["set", "not-a-uuid", "31.77", "35.21"], factory) == 1
    [unchanged] = _rows(engine)
    assert (unchanged["status"], unchanged["location"]) == ("needs_location", None)

    assert store_locations.run(["set", str(row["id"]), "31.77", "35.21"], factory) == 0
    [located] = _rows(engine)
    assert (located["location_source"], located["status"]) == ("manual", "active")
    assert (located["lat"], located["lng"]) == pytest.approx((31.77, 35.21))
    assert _comparable(factory) == [row["id"]]
    assert _needing(factory) == []
    capsys.readouterr()
    assert store_locations.run(["list"], factory) == 0
    assert capsys.readouterr().out == ""
    assert store_locations.run(["move"], factory) == 2


@pytest.mark.parametrize(("lat", "lng"), [(-91, 35.0), (35.21, 31.77), (40.0, 35.0), (31.7, 37.0)])
def test_manual_coordinates_out_of_range(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID, lat: float, lng: float
) -> None:
    _handle(factory, chain_id, FakeGeocoder(point=None), _file(_store()))
    [store_id] = _needing(factory)
    with factory() as session, pytest.raises(ValueError, match="out of range"):
        catalog_service.set_store_location_manual(session, store_id, lat, lng)
    [row] = _rows(engine)
    assert (row["status"], row["location"]) == ("needs_location", None)


def test_an_online_store_gets_no_manual_location(
    engine: Engine, factory: sessionmaker[Session], chain_id: uuid.UUID
) -> None:
    _handle(factory, chain_id, FakeGeocoder(), _file(_store(store_type="2")))
    [row] = _rows(engine)
    with factory() as session, pytest.raises(ValueError, match="online"):
        catalog_service.set_store_location_manual(session, row["id"], 31.77, 35.21)
    [row] = _rows(engine)
    assert (row["status"], row["location"]) == ("online", None)
    assert _comparable(factory) == []


def test_comparable_stores_by_chain(factory: sessionmaker[Session], chain_id: uuid.UUID) -> None:
    with factory() as session:
        other = catalog_service.ensure_chain(session, "7290000000002", "רשת אחרת")
        session.commit()
    _handle(factory, chain_id, FakeGeocoder(), _file(_store()))
    _handle(factory, other, FakeGeocoder(), _file(_store()))
    with factory() as session:
        mine = catalog_service.comparable_store_ids(session, chain_id)
        theirs = catalog_service.comparable_store_ids(session, other)
        both = catalog_service.comparable_store_ids(session)
    assert len(mine) == len(theirs) == 1
    assert set(both) == {*mine, *theirs}


def test_the_schema(engine: Engine) -> None:
    insp = inspect(engine)
    uniques = [u["column_names"] for u in insp.get_unique_constraints("stores")]
    assert ["chain_id", "gov_store_code"] in uniques
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_stores_location'")
        ).scalar_one()
        column_type = conn.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'stores'::regclass AND attname = 'location'"
            )
        ).scalar_one()
    assert "USING gist" in definition
    assert column_type == "geography(Point,4326)"


def test_the_checks(engine: Engine, chain_id: uuid.UUID) -> None:
    sql = text(
        "INSERT INTO stores (id, chain_id, gov_store_code, name, name_norm, address, status, "
        "location_source, last_seen_at, created_at, updated_at) VALUES "
        "(:id, :chain, '1', 'n', 'n', 'a', :status, :source, now(), now(), now())"
    )
    for status, source in (("closed", None), ("active", "guessed")):
        with pytest.raises(Exception, match="ck_stores_"), engine.begin() as conn:
            conn.execute(
                sql, {"id": uuid.uuid4(), "chain": chain_id, "status": status, "source": source}
            )


def test_models_match_the_migrations(stores_url: str) -> None:
    command.check(alembic_config(stores_url))  # raises when autogenerate would find a change


def test_stores_migration_roundtrip_adds_no_data(db_url: str) -> None:
    url = create_database(db_url, "cw_stores_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    try:
        command.upgrade(cfg, "0007")
        assert "stores" not in inspect(eng).get_table_names()
        command.upgrade(cfg, "0008")
        with eng.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM stores")).scalar_one() == 0
        command.downgrade(cfg, "0007")
        tables = set(inspect(eng).get_table_names())
        assert "stores" not in tables
        assert {"chains", "ingestion_runs", "ingestion_files"} <= tables
    finally:
        eng.dispose()
