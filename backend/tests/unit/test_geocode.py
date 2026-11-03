"""NominatimGeocoder and its request spacing, with a fake fetch: no network."""

import io
import logging
import threading
import urllib.error
from collections.abc import Callable
from http.client import BadStatusLine, IncompleteRead
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import DEFAULT_NOMINATIM_URL, Settings
from app.core.errors import AppError
from app.modules.geo import service
from app.modules.geo.service import (
    MAX_WAIT_SECONDS,
    MIN_INTERVAL_SECONDS,
    GeoPoint,
    NominatimGeocoder,
    RequestSpacer,
    _http_get,
)

URL = "https://nominatim.test/search"
ADDRESS = "הרצל 1, תל אביב"
FOUND = b'[{"lat": "32.06", "lon": "34.77", "display_name": "x"}]'


class _FakeTime:
    """Sleeping moves the clock, so the tests take no real time."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _geocoder(fetch: Callable[[str], bytes]) -> NominatimGeocoder:
    fake = _FakeTime()
    return NominatimGeocoder(URL, fetch=fetch, spacer=RequestSpacer(fake.clock, fake.sleep))


def _raising(exc: Exception) -> Callable[[str], bytes]:
    def fetch(_url: str) -> bytes:
        raise exc

    return fetch


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, status, "error", None, io.BytesIO(b""))  # type: ignore[arg-type]


def test_the_url_comes_from_the_settings() -> None:
    assert Settings().NOMINATIM_URL == DEFAULT_NOMINATIM_URL
    service._geocoder_for.cache_clear()
    geocoder = service.get_geocoder(Settings(NOMINATIM_URL=URL))
    assert isinstance(geocoder, NominatimGeocoder)
    assert geocoder._url == URL
    service._geocoder_for.cache_clear()


def test_found_asks_for_one_result_in_israel_and_returns_the_first() -> None:
    seen: list[str] = []

    def fetch(url: str) -> bytes:
        seen.append(url)
        return b'[{"lat": "32.06", "lon": "34.77"}, {"lat": "1", "lon": "2"}]'

    assert _geocoder(fetch).locate(ADDRESS) == GeoPoint(lat=32.06, lng=34.77)
    parts = urlsplit(seen[0])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == URL
    query = parse_qs(parts.query)
    assert query["q"] == [ADDRESS]
    assert query["countrycodes"] == ["il"]
    assert query["limit"] == ["1"]
    assert query["format"] == ["jsonv2"]


def test_no_results_is_none() -> None:
    assert _geocoder(lambda _url: b"[]").locate(ADDRESS) is None


@pytest.mark.parametrize(
    "fetch",
    [
        _raising(TimeoutError("timed out")),
        _raising(urllib.error.URLError("no route")),
        _raising(_http_error(429)),
        _raising(_http_error(500)),
        _raising(IncompleteRead(b"[")),
        _raising(BadStatusLine("nonsense")),
        lambda _url: b"<html>a proxy page</html>",
        lambda _url: b'{"error": "Unable to geocode"}',
        lambda _url: b'[{"lat": "32.06"}]',
        lambda _url: b'[{"lat": "north", "lon": "34"}]',
        lambda _url: b'[{"lat": "NaN", "lon": "34"}]',
        lambda _url: b'[{"lat": "132", "lon": "34"}]',
        lambda _url: b'[{"lat": "32", "lon": "200"}]',
        lambda _url: b'[{"lat": "32", "lon": "NaN"}]',
        lambda _url: b'[{"lat": 1' + b"0" * 400 + b', "lon": "34"}]',  # OverflowError
        lambda _url: b"[" * 1_000_000,  # RecursionError
        lambda _url: b"[1]",
        lambda _url: b"",
    ],
)
def test_any_failure_is_unavailable_without_the_address(
    fetch: Callable[[str], bytes], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(AppError) as err:
        _geocoder(fetch).locate(ADDRESS)
    assert err.value.status == 503
    assert err.value.code == "geocoding_unavailable"
    assert ADDRESS not in err.value.message_he
    assert err.value.__suppress_context__
    assert ADDRESS not in caplog.text
    assert "geocoding_failed" in caplog.text


def test_failure_logs_keep_out_an_error_that_quotes_the_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    def fetch(url: str) -> bytes:
        raise urllib.error.URLError(f"failed for {url}")

    with pytest.raises(AppError):
        _geocoder(fetch).locate(ADDRESS)
    assert "nominatim.test" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_http_error(429), 429),
        (_http_error(500), 500),
        (TimeoutError("timed out"), None),
    ],
)
def test_the_failure_log_tells_the_http_status(
    exc: Exception, expected: int | None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(AppError):
        _geocoder(_raising(exc)).locate(ADDRESS)
    record = next(r for r in caplog.records if r.getMessage() == "geocoding_failed")
    assert vars(record)["http_status"] == expected


def test_get_geocoder_keeps_one_instance_per_url() -> None:
    """The request spacing lives in the instance: a new one per request would drop the limit."""
    service._geocoder_for.cache_clear()
    first = service.get_geocoder(Settings(NOMINATIM_URL=URL))
    assert service.get_geocoder(Settings(NOMINATIM_URL=URL)) is first
    assert service.get_geocoder(Settings(NOMINATIM_URL=f"{URL}/other")) is not first
    service._geocoder_for.cache_clear()


def test_http_get_reads_at_most_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(_request: Any, timeout: float) -> io.BytesIO:
        return io.BytesIO(b"x" * (service.MAX_RESPONSE_BYTES + 10))

    monkeypatch.setattr(service, "urlopen", fake_urlopen)
    assert len(_http_get(URL)) == service.MAX_RESPONSE_BYTES


def test_the_request_identifies_us_and_has_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> io.BytesIO:
        seen["agent"] = request.get_header("User-agent")
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return io.BytesIO(FOUND)

    monkeypatch.setattr(service, "urlopen", fake_urlopen)
    assert _http_get(f"{URL}?q=x") == FOUND
    assert seen["url"] == f"{URL}?q=x"
    assert "CartWise" in seen["agent"]
    assert seen["timeout"] == service.TIMEOUT_SECONDS


def test_requests_are_a_second_apart() -> None:
    fake = _FakeTime()
    sent_at: list[float] = []

    def fetch(_url: str) -> bytes:
        sent_at.append(fake.now)
        return FOUND

    geocoder = NominatimGeocoder(URL, fetch=fetch, spacer=RequestSpacer(fake.clock, fake.sleep))
    for _ in range(3):
        geocoder.locate(ADDRESS)
    assert sent_at == [1000.0, 1000.0 + MIN_INTERVAL_SECONDS, 1000.0 + 2 * MIN_INTERVAL_SECONDS]


def test_no_wait_after_a_quiet_second() -> None:
    fake = _FakeTime()
    spacer = RequestSpacer(fake.clock, fake.sleep)
    assert spacer.wait_for_turn()
    fake.now += MIN_INTERVAL_SECONDS
    assert spacer.wait_for_turn()
    assert fake.sleeps == []


def test_a_queue_that_is_too_long_fails_without_a_request() -> None:
    """Time stands still here, so every call keeps its reserved turn."""
    spacer = RequestSpacer(clock=lambda: 1000.0, sleep=lambda _seconds: None)
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return FOUND

    geocoder = NominatimGeocoder(URL, fetch=fetch, spacer=spacer)
    allowed = int(MAX_WAIT_SECONDS / MIN_INTERVAL_SECONDS) + 1
    for _ in range(allowed):
        geocoder.locate(ADDRESS)
    with pytest.raises(AppError) as err:
        geocoder.locate(ADDRESS)
    assert err.value.code == "geocoding_unavailable"
    assert len(fetched) == allowed


def test_concurrent_callers_get_separate_turns() -> None:
    waits: list[float] = []
    lock = threading.Lock()

    def sleep(seconds: float) -> None:
        with lock:
            waits.append(seconds)

    spacer = RequestSpacer(clock=lambda: 1000.0, sleep=sleep)
    threads = [threading.Thread(target=spacer.wait_for_turn) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(waits) == [1.0, 2.0, 3.0]


def test_a_spacer_with_no_wait_limit_never_refuses() -> None:
    spacer = RequestSpacer(clock=lambda: 1000.0, sleep=lambda _seconds: None, max_wait=None)
    allowed = int(MAX_WAIT_SECONDS / MIN_INTERVAL_SECONDS) + 1
    assert all(spacer.wait_for_turn() for _ in range(allowed + 10))


def test_the_worker_geocoder_waits_with_no_limit() -> None:
    service._worker_geocoder_for.cache_clear()
    geocoder = service.worker_geocoder(Settings(NOMINATIM_URL=URL))
    assert isinstance(geocoder, NominatimGeocoder)
    assert geocoder._url == URL
    assert geocoder._spacer._max_wait is None
    assert service.worker_geocoder(Settings(NOMINATIM_URL=URL)) is geocoder
    assert geocoder is not service.default_geocoder(Settings(NOMINATIM_URL=URL))
    service._worker_geocoder_for.cache_clear()
