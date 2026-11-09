"""Scheduled ingestion (Story 3.2), against Postgres, with fake adapters: no network."""

import functools
import gzip
import hashlib
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import make_engine
from app.modules.catalog import service as catalog_service
from app.modules.geo.service import GeoPoint
from app.modules.ingestion import service
from app.modules.ingestion.adapters import RemoteFile, remote_file
from app.modules.ingestion.decode import decode_xml
from app.modules.ingestion.service import DEFAULT_HANDLERS, RunSummary, ingest_chain
from app.worker.jobs import ingest_chain as ingest_job
from tests.integration.pg import alembic_config, create_database

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingestion"
CODE = "7290000000001"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

STORES = f"Stores{CODE}-000-202611030200.xml"
PRICE = f"PriceFull{CODE}-001-005-20261103-010000.gz"
PROMO = f"PromoFull{CODE}-001-005-20261103-010000.gz"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _good_files() -> dict[str, bytes | Exception]:
    return {
        STORES: _fixture("stores.utf16.xml"),
        PRICE: gzip.compress(_fixture("price_full.xml"), mtime=0),
        PROMO: gzip.compress(_fixture("promo_full.xml"), mtime=0),
    }


class FakeAdapter:
    key = "fake"
    gov_chain_code = CODE
    name = "רשת בדויה"

    def __init__(
        self,
        files: dict[str, bytes | Exception],
        listing_error: Exception | None = None,
    ) -> None:
        self.files = files
        self.listing_error = listing_error
        self.fetched: list[str] = []

    def list_files(self) -> list[RemoteFile]:
        if self.listing_error is not None:
            raise self.listing_error
        listed = [
            remote_file(name, f"https://files.test/{name}?sig=S", CODE) for name in self.files
        ]
        return [f for f in listed if f is not None]

    def fetch(self, file: RemoteFile) -> bytes:
        self.fetched.append(file.name)
        result = self.files[file.name]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(scope="module")
def ingestion_url(db_url: str) -> str:
    """A database of its own: these tests truncate and count rows."""
    url = create_database(db_url, "cw_ingestion")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(ingestion_url: str) -> Iterator[Engine]:
    eng = make_engine(ingestion_url)
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
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _ingest(factory: sessionmaker[Session], adapter: FakeAdapter, **kwargs: Any) -> RunSummary:
    summary = ingest_chain(factory, adapter, now=lambda: NOW, **kwargs)
    assert summary is not None
    return summary


def _rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql), params)]


def _runs(engine: Engine) -> list[dict[str, Any]]:
    return _rows(engine, "SELECT * FROM ingestion_runs ORDER BY started_at, id")


def _files(engine: Engine) -> list[dict[str, Any]]:
    return _rows(engine, "SELECT * FROM ingestion_files ORDER BY created_at, file_name, id")


def test_a_good_run(engine: Engine, factory: sessionmaker[Session]) -> None:
    files = _good_files()
    summary = _ingest(factory, FakeAdapter(files))

    assert summary.status == "succeeded"
    assert (summary.files_seen, summary.files_ingested, summary.files_skipped) == (3, 3, 0)
    assert (summary.files_failed, summary.records) == (0, 2 + 3 + 2)

    chain = _rows(engine, "SELECT id, name, gov_chain_code FROM chains")
    assert [(c["name"], c["gov_chain_code"]) for c in chain] == [("רשת בדויה", CODE)]

    [run] = _runs(engine)
    assert run["id"] == summary.run_id
    assert run["chain_id"] == chain[0]["id"]
    assert run["status"] == "succeeded"
    assert run["started_at"] == NOW
    assert run["finished_at"] == NOW
    assert run["files_seen"] == 3
    assert run["files_ingested"] == 3
    assert run["records"] == 7
    assert run["error"] is None

    rows = {row["file_name"]: row for row in _files(engine)}
    assert set(rows) == {STORES, PRICE, PROMO}
    for name, row in rows.items():
        data = files[name]
        assert isinstance(data, bytes)
        assert row["status"] == "succeeded"
        assert row["run_id"] == summary.run_id
        assert row["file_hash"] == hashlib.sha256(data).hexdigest()
        assert row["size_bytes"] == len(data)
        assert row["error"] is None
    assert (rows[STORES]["kind"], rows[STORES]["records"]) == ("stores", 2)
    assert (rows[PRICE]["kind"], rows[PRICE]["records"]) == ("price_full", 3)
    assert (rows[PROMO]["kind"], rows[PROMO]["records"]) == ("promo_full", 2)


@pytest.mark.parametrize(
    ("broken", "error_type"),
    [
        (gzip.compress(b"<Root><Item/></Root>")[:15], ("EOFError", "BadGzipFile")),
        (gzip.compress(b"<Root><Item></Root>"), ("ParseError",)),
        (b"\xff\xfe" + b"\x00\xd8", ("UnicodeDecodeError",)),
    ],
)
def test_a_broken_file_fails_alone(
    engine: Engine,
    factory: sessionmaker[Session],
    broken: bytes,
    error_type: tuple[str, ...],
) -> None:
    files = _good_files()
    files[PRICE] = broken
    summary = _ingest(factory, FakeAdapter(files))

    assert summary.status == "partial"
    # With no prices, no product is known: the promotions file fails too, to be taken again.
    assert (summary.files_ingested, summary.files_failed, summary.records) == (1, 2, 2)
    rows = {row["file_name"]: row for row in _files(engine)}
    assert rows[STORES]["status"] == "succeeded"
    assert rows[PROMO]["status"] == "failed"
    assert rows[PROMO]["error"] == "ValueError: no promotion matched a known product"
    failed = rows[PRICE]
    assert failed["status"] == "failed"
    assert failed["records"] == 0
    assert failed["error"].startswith(error_type)
    assert failed["file_hash"] is not None
    [run] = _runs(engine)
    assert (run["status"], run["files_failed"], run["records"]) == ("partial", 2, 2)
    assert run["error"] == "2 of 3 files failed"


def test_a_failing_handler_is_rolled_back_alone(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    def writes_then_fails(session: Session, chain_id: uuid.UUID, root: Any) -> int:
        catalog_service.ensure_chain(session, "7290000000099", "נכתב ובוטל")
        raise RuntimeError("handler broke")

    def writes(session: Session, chain_id: uuid.UUID, root: Any) -> int:
        catalog_service.ensure_chain(session, "7290000000098", "נכתב ונשמר")
        return 1

    handlers = {**DEFAULT_HANDLERS, "price_full": writes_then_fails, "promo_full": writes}
    summary = _ingest(factory, FakeAdapter(_good_files()), handlers=handlers)

    assert summary.status == "partial"
    codes = {row["gov_chain_code"] for row in _rows(engine, "SELECT gov_chain_code FROM chains")}
    assert codes == {CODE, "7290000000098"}
    [failed] = [row for row in _files(engine) if row["status"] == "failed"]
    assert failed["error"] == "RuntimeError: handler broke"


def test_a_failed_download(engine: Engine, factory: sessionmaker[Session]) -> None:
    files = _good_files()
    files[PROMO] = OSError("connection reset by https://files.test/x?sig=SECRET")
    adapter = FakeAdapter(files)
    summary = _ingest(factory, adapter)

    assert summary.status == "partial"
    assert sorted(adapter.fetched) == sorted([STORES, PRICE, PROMO])
    [failed] = [row for row in _files(engine) if row["status"] == "failed"]
    assert failed["file_name"] == PROMO
    assert failed["error"] == "OSError: connection reset by <url>"
    assert failed["file_hash"] is None
    assert failed["size_bytes"] is None


def test_every_file_failing_fails_the_run(engine: Engine, factory: sessionmaker[Session]) -> None:
    files: dict[str, bytes | Exception] = {name: OSError("down") for name in _good_files()}
    summary = _ingest(factory, FakeAdapter(files))
    assert summary.status == "failed"
    [run] = _runs(engine)
    assert run["status"] == "failed"
    assert run["files_failed"] == 3
    assert run["error"] == "all 3 files failed"


def test_a_second_run_skips_what_was_ingested(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    _ingest(factory, FakeAdapter(_good_files()))
    summary = _ingest(factory, FakeAdapter(_good_files()))

    assert summary.status == "succeeded"
    assert (summary.files_seen, summary.files_skipped, summary.files_ingested) == (3, 3, 0)
    assert summary.records == 0
    assert len(_files(engine)) == 3
    runs = _runs(engine)
    assert len(runs) == 2
    assert runs[1]["files_skipped"] == 3


def test_the_same_name_with_other_bytes_is_ingested(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    _ingest(factory, FakeAdapter(_good_files()))
    files = _good_files()
    files[PRICE] = gzip.compress(
        "<Root><StoreId>101</StoreId><Items><Item><ItemCode>1000000000001</ItemCode>"
        "<ItemType>1</ItemType><ItemName>חלב בדוי 3%</ItemName><ItemPrice>7.10</ItemPrice>"
        "</Item></Items></Root>".encode()
    )
    summary = _ingest(factory, FakeAdapter(files))

    assert (summary.files_ingested, summary.files_skipped, summary.records) == (1, 2, 1)
    price_rows = [row for row in _files(engine) if row["file_name"] == PRICE]
    assert [row["status"] for row in price_rows] == ["succeeded", "succeeded"]
    assert price_rows[0]["file_hash"] != price_rows[1]["file_hash"]


def test_a_file_that_failed_is_ingested_again(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    files = _good_files()

    def fails_once(session: Session, chain_id: uuid.UUID, root: Any) -> int:
        raise RuntimeError("handler broke")

    # The same bytes fail first (in the handler), so the failed row has the same hash.
    handlers = {**DEFAULT_HANDLERS, "price_full": fails_once}
    first = _ingest(factory, FakeAdapter(files), handlers=handlers)
    # The promotions file fails with it: no product is known yet.
    assert first.files_failed == 2

    second = _ingest(factory, FakeAdapter(files))
    assert (second.files_ingested, second.files_skipped, second.files_failed) == (2, 1, 0)
    price_rows = [row for row in _files(engine) if row["file_name"] == PRICE]
    assert [row["status"] for row in price_rows] == ["failed", "succeeded"]
    assert price_rows[0]["file_hash"] == price_rows[1]["file_hash"]


def test_only_the_latest_version_of_a_store_is_taken(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    later = f"PriceFull{CODE}-001-005-20261103-070000.gz"
    files = _good_files()
    files[later] = gzip.compress(b"<Root><Item/><Item/></Root>")
    adapter = FakeAdapter(files)
    summary = _ingest(factory, adapter)

    assert summary.files_seen == 3
    assert PRICE not in adapter.fetched
    names = {row["file_name"] for row in _files(engine)}
    assert names == {STORES, later, PROMO}


def test_a_failed_listing_fails_the_run(engine: Engine, factory: sessionmaker[Session]) -> None:
    error = ValueError("no csrftoken at https://portal.test/login?sig=SECRET")
    summary = _ingest(factory, FakeAdapter({}, listing_error=error))

    assert summary.status == "failed"
    assert summary.files_seen == 0
    [run] = _runs(engine)
    assert run["status"] == "failed"
    assert run["finished_at"] == NOW
    assert run["error"] == "ValueError: no csrftoken at <url>"
    assert _files(engine) == []


def test_a_listing_with_no_files_fails_the_run(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    other_chain: dict[str, bytes | Exception] = {
        "PriceFull7290000000002-001-202611030300.gz": b"<Root/>"
    }
    summary = _ingest(factory, FakeAdapter(other_chain))
    assert summary.status == "failed"
    [run] = _runs(engine)
    assert (run["status"], run["files_seen"], run["error"]) == ("failed", 0, "no files listed")


def test_a_long_error_is_cut(engine: Engine, factory: sessionmaker[Session]) -> None:
    _ingest(factory, FakeAdapter({}, listing_error=RuntimeError("x" * 2000)))
    [run] = _runs(engine)
    assert len(run["error"]) == service.MAX_ERROR_LENGTH
    assert run["error"].startswith("RuntimeError: xxx")


def test_a_run_while_another_holds_the_lock(engine: Engine, factory: sessionmaker[Session]) -> None:
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": f"ingest:{CODE}"}
        ).scalar_one()
        try:
            assert ingest_chain(factory, FakeAdapter(_good_files())) is None
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": f"ingest:{CODE}"})
            conn.commit()
    assert _runs(engine) == []
    # The lock is released: the next run goes ahead.
    assert _ingest(factory, FakeAdapter(_good_files())).status == "succeeded"


class _BlockingAdapter(FakeAdapter):
    def __init__(self, files: dict[str, bytes | Exception]) -> None:
        super().__init__(files)
        self.listing = threading.Event()
        self.release = threading.Event()

    def list_files(self) -> list[RemoteFile]:
        self.listing.set()
        assert self.release.wait(timeout=30)
        return super().list_files()


def test_concurrent_runs_of_a_chain(engine: Engine, factory: sessionmaker[Session]) -> None:
    blocking = _BlockingAdapter(_good_files())
    results: list[RunSummary | None] = []
    thread = threading.Thread(
        target=lambda: results.append(ingest_chain(factory, blocking, now=lambda: NOW))
    )
    thread.start()
    try:
        assert blocking.listing.wait(timeout=30)
        assert ingest_chain(factory, FakeAdapter(_good_files())) is None
    finally:
        blocking.release.set()
        thread.join(timeout=30)
    [summary] = results
    assert summary is not None
    assert summary.status == "succeeded"
    assert len(_runs(engine)) == 1


def test_an_abandoned_run_is_marked(engine: Engine, factory: sessionmaker[Session]) -> None:
    with factory() as session:
        chain_id = catalog_service.ensure_chain(session, CODE, "רשת בדויה")
        session.commit()
    old = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ingestion_runs (id, chain_id, started_at, status) "
                "VALUES (:id, :chain, :at, 'running')"
            ),
            {"id": old, "chain": chain_id, "at": NOW - timedelta(hours=7)},
        )
    summary = _ingest(factory, FakeAdapter(_good_files()))

    runs = {run["id"]: run for run in _runs(engine)}
    assert runs[old]["status"] == "abandoned"
    assert runs[old]["finished_at"] == NOW
    assert runs[summary.run_id]["status"] == "succeeded"


def test_a_file_over_the_xml_cap_fails(
    engine: Engine, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "decode_xml", functools.partial(decode_xml, max_xml_bytes=5000))
    files = _good_files()
    files[PRICE] = gzip.compress(b"<Root>" + b" " * 10_000 + b"</Root>")
    summary = _ingest(factory, FakeAdapter(files))

    assert summary.status == "partial"
    failed = {row["file_name"]: row for row in _files(engine) if row["status"] == "failed"}
    assert failed[PRICE]["error"].startswith("XmlTooLargeError")


def test_a_download_over_the_cap_fails(
    engine: Engine, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _good_files()
    cap = max(len(data) for data in files.values() if isinstance(data, bytes))
    monkeypatch.setattr(service, "MAX_DOWNLOAD_BYTES", cap)
    files[STORES] = b" " * (cap + 1)
    summary = _ingest(factory, FakeAdapter(files))
    failed = {row["file_name"]: row for row in _files(engine) if row["status"] == "failed"}
    assert failed[STORES]["error"].startswith("DownloadTooLargeError")
    # With no stores, the store's price and promotion files fail too, to be taken next run.
    assert failed[PRICE]["error"] == "UnknownStoreError: unknown store 101"
    assert failed[PROMO]["error"] == "UnknownStoreError: unknown store 101"
    assert summary.files_failed == 3


def test_ensure_chain_is_idempotent(engine: Engine, factory: sessionmaker[Session]) -> None:
    with factory() as session:
        first = catalog_service.ensure_chain(session, CODE, "רשת בדויה")
        second = catalog_service.ensure_chain(session, CODE, "שם אחר")
        session.commit()
    assert first == second
    names = _rows(engine, "SELECT name FROM chains")
    assert names == [{"name": "רשת בדויה"}]


def test_the_job_runs_one_chain(engine: Engine, factory: sessionmaker[Session]) -> None:
    adapter = FakeAdapter(_good_files())
    located: list[str] = []

    class Geocoder:
        def locate(self, address: str) -> GeoPoint | None:
            located.append(address)
            return GeoPoint(lat=31.78, lng=35.22)

    summary = ingest_job.run(
        "fake", session_factory=factory, adapters=lambda: {"fake": adapter}, geocoder=Geocoder()
    )
    assert summary is not None
    assert summary.status == "succeeded"
    assert summary.chain_key == "fake"
    # The job's handlers geocode stores, with the geocoder it was given.
    assert len(located) == 2
    statuses = _rows(engine, "SELECT status FROM stores")
    assert [row["status"] for row in statuses] == ["active", "active"]


def test_the_job_uses_the_worker_geocoder_by_default(
    engine: Engine, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    located: list[str] = []

    class Geocoder:
        def locate(self, address: str) -> GeoPoint | None:
            located.append(address)
            return GeoPoint(lat=31.78, lng=35.22)

    monkeypatch.setattr(ingest_job, "worker_geocoder", lambda _settings: Geocoder())
    adapter = FakeAdapter(_good_files())
    summary = ingest_job.run("fake", session_factory=factory, adapters=lambda: {"fake": adapter})
    assert summary is not None
    assert summary.status == "succeeded"
    assert len(located) == 2
    statuses = _rows(engine, "SELECT status FROM stores")
    assert [row["status"] for row in statuses] == ["active", "active"]
