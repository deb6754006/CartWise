"""geo: business logic. Other modules use geo data only through this file.

An address passes through here on its way to the geocoder and back. It is not stored or cached,
and it never goes into a log line or an error message. That is why failures are reported by
exception type only, and re-raised `from None`: the URL carries the address.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from http.client import HTTPException
from typing import Annotated, Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.errors import AppError

logger = logging.getLogger("app.geo")

ADDRESS_NOT_FOUND_HE = "לא מצאנו את הכתובת"
GEOCODING_UNAVAILABLE_HE = "לא הצלחנו לבדוק את הכתובת"

# Nominatim's usage policy asks for an identifying User-Agent.
USER_AGENT = "CartWise/1.0 (+https://github.com/deb6754006/CartWise)"
TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 1_000_000
# At most one request per this many seconds, from this process.
MIN_INTERVAL_SECONDS = 1.0
# A request that would have to wait longer than this fails instead of tying up a worker thread.
MAX_WAIT_SECONDS = 3.0


@dataclass(frozen=True, slots=True)
class GeoPoint:
    lat: float
    lng: float


def address_not_found() -> AppError:
    return AppError("address_not_found", ADDRESS_NOT_FOUND_HE, status=404)


def geocoding_unavailable() -> AppError:
    return AppError("geocoding_unavailable", GEOCODING_UNAVAILABLE_HE, status=503)


class Geocoder(Protocol):
    def locate(self, address: str) -> GeoPoint | None:
        """The first match in Israel, or None. Raises AppError 503 geocoding_unavailable."""
        ...


class RequestSpacer:
    """Spaces calls MIN_INTERVAL_SECONDS apart, each one waiting for its own turn.

    A call whose turn is more than max_wait seconds away fails at once; max_wait None waits
    however long it takes (the worker, where no request is waiting for an answer).
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_wait: float | None = MAX_WAIT_SECONDS,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._max_wait = max_wait
        self._next_free = 0.0
        self._lock = threading.Lock()

    def wait_for_turn(self) -> bool:
        """Returns once it is this call's turn, or False at once if that is too far away."""
        with self._lock:
            now = self._clock()
            turn = max(now, self._next_free)
            wait = turn - now
            if self._max_wait is not None and wait > self._max_wait:
                return False
            self._next_free = turn + MIN_INTERVAL_SECONDS
        if wait > 0:
            self._sleep(wait)
        return True


def _http_get(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 (URL from our config)
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        body: bytes = response.read(MAX_RESPONSE_BYTES)
    return body


def _first_point(body: bytes) -> GeoPoint | None:
    """Raises (see the except in locate) on anything but a list of results."""
    results = json.loads(body)
    if not isinstance(results, list):
        raise ValueError("not a list")
    if not results:
        return None
    lat, lng = float(results[0]["lat"]), float(results[0]["lon"])
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):  # also rejects NaN
        raise ValueError("coordinates out of range")
    return GeoPoint(lat=lat, lng=lng)


class NominatimGeocoder:
    def __init__(
        self,
        url: str,
        fetch: Callable[[str], bytes] = _http_get,
        spacer: RequestSpacer | None = None,
    ) -> None:
        self._url = url
        self._fetch = fetch
        self._spacer = spacer if spacer is not None else RequestSpacer()

    def locate(self, address: str) -> GeoPoint | None:
        if not self._spacer.wait_for_turn():
            logger.warning("geocoding_busy")
            raise geocoding_unavailable()
        query = urlencode({"q": address, "format": "jsonv2", "limit": 1, "countrycodes": "il"})
        try:
            return _first_point(self._fetch(f"{self._url}?{query}"))
        except (
            OSError,
            HTTPException,
            ValueError,
            KeyError,
            TypeError,
            OverflowError,
            RecursionError,
        ) as exc:
            # OSError includes URLError, HTTPError (429 and the like) and timeouts.
            http_status = exc.code if isinstance(exc, HTTPError) else None
            logger.warning(
                "geocoding_failed",
                extra={"error": type(exc).__name__, "http_status": http_status},
            )
            raise geocoding_unavailable() from None


def locate_address(geocoder: Geocoder, address: str) -> GeoPoint:
    point = geocoder.locate(address)
    if point is None:
        raise address_not_found()
    return point


@lru_cache(maxsize=4)
def _geocoder_for(url: str) -> NominatimGeocoder:
    # One instance per URL: the request spacing is per process.
    return NominatimGeocoder(url)


def default_geocoder(settings: Settings) -> Geocoder:
    """The configured geocoder, outside FastAPI (for the worker)."""
    return _geocoder_for(settings.NOMINATIM_URL)


@lru_cache(maxsize=4)
def _worker_geocoder_for(url: str) -> NominatimGeocoder:
    # Its own spacer, which waits with no limit: the worker's chain jobs run in parallel threads.
    return NominatimGeocoder(url, spacer=RequestSpacer(max_wait=None))


def worker_geocoder(settings: Settings) -> Geocoder:
    """The configured geocoder for the worker: requests wait their turn instead of failing."""
    return _worker_geocoder_for(settings.NOMINATIM_URL)


def get_geocoder(settings: Annotated[Settings, Depends(get_settings)]) -> Geocoder:
    """FastAPI dependency; tests override it with a fake geocoder."""
    return default_geocoder(settings)
