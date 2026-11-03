"""The chain adapters and file selection (Story 3.2), with fake HTTP: no network."""

import io
import ssl
import urllib.error
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import Settings
from app.modules.ingestion import adapters
from app.modules.ingestion.adapters import (
    CarrefourAdapter,
    CerberusAdapter,
    HttpStatusError,
    PortalFormatError,
    RemoteFile,
    ShufersalAdapter,
    UrllibClient,
    build_adapters,
    latest_per_store,
    parse_file_name,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingestion"
SHUFERSAL = "https://shufersal.test"
CERBERUS = "https://cerberus.test"
CARREFOUR = "https://carrefour.test"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _file(name: str) -> RemoteFile:
    parsed = parse_file_name(name)
    assert parsed is not None
    file = adapters.remote_file(name, f"https://x.test/{name}", parsed.chain_code)
    assert file is not None
    return file


# ---------------------------------------------------------------- file names


@pytest.mark.parametrize(
    ("name", "kind", "store", "stamp"),
    [
        ("PriceFull7290027600007-001-202611030300.gz", "price_full", "001", "20261103030000"),
        ("PromoFull7290058140886-001-202611030010.gz", "promo_full", "001", "20261103001000"),
        ("Stores7290027600007-000-202611030201.xml", "stores", None, "20261103020100"),
        ("Stores7290055700007-000-202611030500", "stores", None, "20261103050000"),
        (
            "PriceFull7290000000000-001-005-20261103-010000",
            "price_full",
            "001-005",
            "20261103010000",
        ),
        (
            "PriceFull7290000000000-001-005-20261103-010000.xml",
            "price_full",
            "001-005",
            "20261103010000",
        ),
        ("PromoFull7290000000000-12-20261103", "promo_full", "12", "20261103000000"),
    ],
)
def test_parse_file_name(name: str, kind: str, store: str | None, stamp: str) -> None:
    parsed = parse_file_name(name)
    assert parsed is not None
    assert (parsed.kind, parsed.store_code, parsed.stamp) == (kind, store, stamp)


@pytest.mark.parametrize(
    "name",
    [
        "Price7290027600007-001-202611030900.gz",  # partial
        "Promo7290027600007-001-202611030900.gz",  # partial
        "PriceFull72900276-001-202611030300.gz",  # not a 13-digit chain code
        "NotAPriceFile.txt",
        "",
    ],
)
def test_other_file_names_are_not_selected(name: str) -> None:
    assert parse_file_name(name) is None


def test_files_of_another_chain_are_skipped() -> None:
    name = "PriceFull7290027600007-001-202611030300.gz"
    assert adapters.remote_file(name, "https://x.test/f", "7290027600007") is not None
    assert adapters.remote_file(name, "https://x.test/f", "7290058140886") is None

    page = f'<script>const path = \'20261103\'; const files = [{{"name": "{name}"}}];</script>'
    get = _FakeGet({f"{CARREFOUR}/": page.encode()})
    assert CarrefourAdapter(CARREFOUR, get).list_files() == []


def test_latest_per_store_keeps_the_latest_version() -> None:
    early = _file("PriceFull7290000000000-001-005-20261103-010000.gz")
    late = _file("PriceFull7290000000000-001-005-20261103-070000.gz")
    other = _file("PriceFull7290000000000-001-006-20261103-010000.gz")
    promo = _file("PromoFull7290000000000-001-005-20261103-010000.gz")
    stores_old = _file("Stores7290000000000-000-20261102-020000.xml")
    stores_new = _file("Stores7290000000000-000-20261103-020000.xml")
    selected = latest_per_store([late, early, promo, other, stores_new, stores_old])
    assert selected == [stores_new, late, other, promo]


def test_latest_per_store_breaks_a_tie_by_the_larger_name() -> None:
    a = _file("PriceFull7290000000000-001-20261103-0100.gz")
    b = _file("PriceFull7290000000000-001-20261103-010000.xml")
    assert a.stamp == b.stamp
    assert latest_per_store([b, a]) == [max(a, b, key=lambda f: f.name)]
    assert latest_per_store([a, b]) == [max(a, b, key=lambda f: f.name)]


# ---------------------------------------------------------------- Shufersal


class _FakeGet:
    def __init__(self, pages: Mapping[str, bytes]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.pages[url]


def _shufersal_page_url(category: int, page: int) -> str:
    return f"{SHUFERSAL}/FileObject/UpdateCategory?catID={category}&storeId=0&page={page}"


def test_shufersal_reads_pages_until_an_empty_one() -> None:
    empty = _fixture("shufersal_empty.html")
    pages = {
        _shufersal_page_url(5, 1): empty,
        _shufersal_page_url(2, 1): _fixture("shufersal_page1.html"),
        _shufersal_page_url(2, 2): _fixture("shufersal_page2.html"),
        _shufersal_page_url(2, 3): empty,
        _shufersal_page_url(4, 1): empty,
    }
    get = _FakeGet(pages)
    adapter = ShufersalAdapter(SHUFERSAL + "/", get)
    files = adapter.list_files()

    names = sorted(f.name for f in files)
    assert names == [
        "PriceFull7290027600007-001-202611020300.gz",
        "PriceFull7290027600007-001-202611030300.gz",
        "PriceFull7290027600007-002-202611030300.gz",
        "PriceFull7290027600007-003-202611030300.gz",
    ]
    assert len(get.urls) == 5
    file = next(f for f in files if f.name == "PriceFull7290027600007-001-202611030300.gz")
    parts = urlsplit(file.url)
    assert parts.netloc == "pricesprodpublic.blob.core.windows.net"
    assert parts.path == "/price/PriceFull7290027600007-001-202611030300.gz"
    # &amp; is unescaped, so the signature survives.
    assert parse_qs(parts.query)["sig"] == ["FAKESIGNATURE"]

    selected = latest_per_store(files)
    assert [f.name for f in selected] == [
        "PriceFull7290027600007-001-202611030300.gz",
        "PriceFull7290027600007-002-202611030300.gz",
        "PriceFull7290027600007-003-202611030300.gz",
    ]

    get.pages = {file.url: b"bytes"}
    assert adapter.fetch(file) == b"bytes"


def _shufersal_store_page(file_name: str) -> bytes:
    url = f"https://pricesprodpublic.blob.core.windows.net/price/{file_name}?sig=FRESH"
    return f'<a href="{url}">x</a>'.encode()


def test_shufersal_refreshes_an_expired_link_once() -> None:
    name = "PromoFull7290027600007-550-202611030300.gz"
    old = _file(name)
    fresh_url = f"https://pricesprodpublic.blob.core.windows.net/price/{name}?sig=FRESH"
    page_url = f"{SHUFERSAL}/FileObject/UpdateCategory?catID=4&storeId=550&page=1"
    calls: list[str] = []

    def get(url: str) -> bytes:
        calls.append(url)
        if url == old.url:
            raise HttpStatusError(403)
        if url == page_url:
            return _shufersal_store_page(name)
        if url == fresh_url:
            return b"fresh bytes"
        raise AssertionError(url)

    assert ShufersalAdapter(SHUFERSAL, get).fetch(old) == b"fresh bytes"
    assert calls == [old.url, page_url, fresh_url]


def test_shufersal_refreshes_a_stores_link_from_store_0() -> None:
    name = "Stores7290027600007-000-202611030201.xml"
    old = _file(name)
    page_url = f"{SHUFERSAL}/FileObject/UpdateCategory?catID=5&storeId=0&page=1"
    calls: list[str] = []

    def get(url: str) -> bytes:
        calls.append(url)
        if url == old.url:
            raise HttpStatusError(403)
        if url == page_url:
            return _shufersal_store_page(name)
        return b"fresh"

    assert ShufersalAdapter(SHUFERSAL, get).fetch(old) == b"fresh"
    assert calls[1] == page_url


def test_shufersal_reraises_when_the_file_is_gone_or_not_403() -> None:
    old = _file("PriceFull7290027600007-001-005-202611030300.gz")
    page_url = f"{SHUFERSAL}/FileObject/UpdateCategory?catID=2&storeId=5&page=1"
    error = HttpStatusError(403)

    def gone(url: str) -> bytes:
        if url == page_url:
            return _shufersal_store_page("PriceFull7290027600007-001-005-202611040300.gz")
        raise error

    with pytest.raises(HttpStatusError) as caught:
        ShufersalAdapter(SHUFERSAL, gone).fetch(old)
    assert caught.value is error

    calls: list[str] = []

    def server_error(url: str) -> bytes:
        calls.append(url)
        raise HttpStatusError(500)

    with pytest.raises(HttpStatusError):
        ShufersalAdapter(SHUFERSAL, server_error).fetch(old)
    assert calls == [old.url]


def test_shufersal_stops_when_a_page_repeats() -> None:
    page = _fixture("shufersal_page1.html")

    def get(url: str) -> bytes:
        return page if "catID=2" in url else _fixture("shufersal_empty.html")

    calls: list[str] = []

    def counting(url: str) -> bytes:
        calls.append(url)
        return get(url)

    files = ShufersalAdapter(SHUFERSAL, counting, max_pages=50).list_files()
    assert len(files) == 2
    assert sum("catID=2" in url for url in calls) == 2


def test_shufersal_stops_at_max_pages() -> None:
    def get(url: str) -> bytes:
        page = int(parse_qs(urlsplit(url).query)["page"][0])
        name = f"PriceFull7290027600007-{page:03d}-202611030300.gz"
        return f'<a href="https://blob.test/p/{name}?sig=x">x</a>'.encode()

    files = ShufersalAdapter(SHUFERSAL, get, max_pages=4).list_files()
    # Four pages for each of the three categories, the same names each time.
    assert len(files) == 4


# ---------------------------------------------------------------- Cerberus


class _FakeCerberus:
    def __init__(self, login: bytes, file_page: bytes, listing: bytes) -> None:
        self.login, self.file_page, self.listing = login, file_page, listing
        self.posts: list[tuple[str, dict[str, str]]] = []
        self.gets: list[str] = []

    def get(self, url: str) -> bytes:
        self.gets.append(url)
        if url == f"{CERBERUS}/login":
            return self.login
        return b"file:" + url.encode()

    def post(self, url: str, form: Mapping[str, str]) -> bytes:
        self.posts.append((url, dict(form)))
        if url == f"{CERBERUS}/login/user":
            return self.file_page
        if url == f"{CERBERUS}/file/json/dir":
            return self.listing
        raise AssertionError(url)


def _cerberus(fake: _FakeCerberus) -> CerberusAdapter:
    return CerberusAdapter(
        "rami_levy", "7290058140886", "רמי לוי", CERBERUS, "PublicUser", fake.get, fake.post
    )


def test_cerberus_logs_in_and_lists_with_the_new_token() -> None:
    fake = _FakeCerberus(
        _fixture("cerberus_login.html"),
        _fixture("cerberus_file.html"),
        _fixture("cerberus_dir.json"),
    )
    adapter = _cerberus(fake)
    files = adapter.list_files()

    login_url, login_form = fake.posts[0]
    assert login_url == f"{CERBERUS}/login/user"
    assert login_form == {
        "r": "",
        "username": "PublicUser",
        "password": "",
        "csrftoken": "LOGIN-TOKEN-1",
    }
    dir_url, dir_form = fake.posts[1]
    assert dir_url == f"{CERBERUS}/file/json/dir"
    assert dir_form["csrftoken"] == "FILE-TOKEN-2"
    assert dir_form["cd"] == "/"
    assert dir_form["iDisplayLength"] == "100000"

    assert sorted(f.name for f in files) == [
        "PriceFull7290058140886-001-202611030010.gz",
        "PromoFull7290058140886-001-202611030010.gz",
        "Stores7290058140886-000-202611030200.xml",
    ]
    file = next(f for f in files if f.kind == "price_full")
    assert file.url == f"{CERBERUS}/file/d/PriceFull7290058140886-001-202611030010.gz"
    assert adapter.fetch(file) == b"file:" + file.url.encode()


def test_cerberus_failed_login_raises() -> None:
    login = _fixture("cerberus_login.html")
    fake = _FakeCerberus(login, login, _fixture("cerberus_dir.json"))
    with pytest.raises(PortalFormatError, match="Cerberus login failed"):
        _cerberus(fake).list_files()
    assert len(fake.posts) == 1


def test_cerberus_skips_unknown_rows_and_other_chains() -> None:
    listing = b"""{"aaData": [{"fname": "PriceFull7290058140886-002-202611030010.gz"},
        {"fname": "PriceFull7290027600007-001-202611030010.gz"}, {"size": 1}, "x"]}"""
    fake = _FakeCerberus(_fixture("cerberus_login.html"), _fixture("cerberus_file.html"), listing)
    names = [f.name for f in _cerberus(fake).list_files()]
    assert names == ["PriceFull7290058140886-002-202611030010.gz"]


def test_cerberus_without_a_token_raises() -> None:
    fake = _FakeCerberus(b"<html>no token</html>", b"", b"")
    with pytest.raises(PortalFormatError):
        _cerberus(fake).list_files()
    assert fake.posts == []


def test_cerberus_without_a_token_on_the_file_page_raises() -> None:
    fake = _FakeCerberus(_fixture("cerberus_login.html"), b"<html>logged out</html>", b"")
    with pytest.raises(PortalFormatError):
        _cerberus(fake).list_files()


def test_cerberus_listing_without_aadata_raises() -> None:
    fake = _FakeCerberus(
        _fixture("cerberus_login.html"), _fixture("cerberus_file.html"), b'{"error": 1}'
    )
    with pytest.raises(PortalFormatError):
        _cerberus(fake).list_files()


# ---------------------------------------------------------------- Carrefour


def test_carrefour_reads_the_embedded_list() -> None:
    get = _FakeGet({f"{CARREFOUR}/": _fixture("carrefour.html")})
    files = CarrefourAdapter(CARREFOUR, get).list_files()
    assert sorted(f.name for f in files) == [
        "PriceFull7290055700007-128-202611030500.gz",
        "PromoFull7290055700007-128-202611030511.gz",
        "Stores7290055700007-000-202611030500.xml",
    ]
    file = next(f for f in files if f.kind == "promo_full")
    assert file.url == f"{CARREFOUR}/20261103/PromoFull7290055700007-128-202611030511.gz"
    assert file.store_code == "128"


@pytest.mark.parametrize(
    "page",
    [
        b"<script>const path = '20261103';</script>",
        b"<script>const files = [];</script>",
        b"<script>const path = '20261103'; const files = [{broken;</script>",
        b"<script>const path = '20261103'; const files = {\"a\": 1};</script>",
    ],
)
def test_carrefour_without_files_raises(page: bytes) -> None:
    with pytest.raises(PortalFormatError):
        CarrefourAdapter(CARREFOUR, _FakeGet({f"{CARREFOUR}/": page})).list_files()


# ---------------------------------------------------------------- build_adapters, UrllibClient


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get(self, url: str) -> bytes:
        self.calls.append(("get", url))
        return b""

    def post(self, url: str, form: Mapping[str, str]) -> bytes:
        self.calls.append(("post", url))
        return b""


def test_build_adapters_uses_the_settings() -> None:
    settings = Settings(
        SHUFERSAL_PRICES_URL=SHUFERSAL,
        CERBERUS_URL=CERBERUS,
        CARREFOUR_PRICES_URL=CARREFOUR,
        CERBERUS_RAMI_LEVY_USERNAME="SomeoneElse",
    )
    clients: list[_RecordingClient] = []

    def factory() -> Any:
        clients.append(_RecordingClient())
        return clients[-1]

    built = build_adapters(settings, factory)
    assert list(built) == list(adapters.CHAIN_KEYS)
    assert [a.gov_chain_code for a in built.values()] == [
        "7290027600007",
        "7290058140886",
        "7290055700007",
    ]
    assert [a.name for a in built.values()] == ["שופרסל", "רמי לוי", "קרפור"]
    # One client per chain: Rami Levy's cookies are its own.
    assert len(clients) == 3
    with pytest.raises(PortalFormatError):
        built["rami_levy"].list_files()
    assert clients[1].calls == [("get", f"{CERBERUS}/login")]


def test_default_settings() -> None:
    settings = Settings()
    assert settings.SHUFERSAL_PRICES_URL == "https://prices.shufersal.co.il"
    assert settings.CERBERUS_URL == "https://url.publishedprices.co.il"
    assert settings.CARREFOUR_PRICES_URL == "https://prices.carrefour.co.il"
    assert settings.CERBERUS_RAMI_LEVY_USERNAME == "RamiLevi"
    assert settings.INGEST_INTERVAL_HOURS == 6


@pytest.mark.parametrize("hours", [0, 7])
def test_interval_is_between_1_and_6_hours(hours: int) -> None:
    with pytest.raises(ValueError, match="INGEST_INTERVAL_HOURS"):
        Settings(INGEST_INTERVAL_HOURS=hours)


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class _FakeOpener:
    def __init__(self, result: bytes | Exception) -> None:
        self.result = result
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: float) -> _Response:
        self.requests.append((request, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return _Response(self.result)


def _client(result: bytes | Exception, max_bytes: int = 100) -> tuple[UrllibClient, _FakeOpener]:
    client = UrllibClient(max_bytes=max_bytes)
    opener = _FakeOpener(result)
    client._opener = opener  # type: ignore[assignment]
    return client, opener


SIGNED = "https://blob.test/f.gz?sig=SECRETSIG"


def test_client_get_and_post() -> None:
    client, opener = _client(b"body")
    assert client.get(SIGNED) == b"body"
    assert client.post("https://cerberus.test/login/user", {"a": "1", "b": ""}) == b"body"
    get, timeout = opener.requests[0]
    assert timeout == adapters.TIMEOUT_SECONDS
    assert get.get_header("User-agent") == adapters.USER_AGENT
    post, _ = opener.requests[1]
    assert post.get_method() == "POST"
    assert post.data == b"a=1&b="


def test_client_caps_the_size() -> None:
    client, _ = _client(b"x" * 101)
    with pytest.raises(adapters.DownloadTooLargeError):
        client.get(SIGNED)


def test_client_refuses_plain_http() -> None:
    client, opener = _client(b"")
    with pytest.raises(PortalFormatError):
        client.get("http://blob.test/f.gz")
    assert opener.requests == []


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError(SIGNED, 403, "Forbidden", None, io.BytesIO(b"")),  # type: ignore[arg-type]
        urllib.error.URLError(f"cannot reach {SIGNED}"),
        TimeoutError("timed out"),
        urllib.error.URLError(ssl.SSLCertVerificationError(f"certificate verify failed {SIGNED}")),
    ],
)
def test_client_errors_never_carry_the_url(error: Exception) -> None:
    client, _ = _client(error)
    with pytest.raises(OSError) as caught:
        client.get(SIGNED)
    assert "SECRETSIG" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert "sig=" not in str(caught.value)
    if isinstance(error, urllib.error.HTTPError):
        assert isinstance(caught.value, HttpStatusError)
        assert caught.value.status == 403
    if isinstance(error, urllib.error.URLError) and isinstance(error.reason, ssl.SSLError):
        # A filtered network (NetFree) shows up as this: the detail is kept.
        assert str(caught.value).startswith("SSLCertVerificationError:")
        assert "certificate verify failed" in str(caught.value)
