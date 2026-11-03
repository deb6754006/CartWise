"""ingestion: a chain's Stores file, to the chain's stores (through catalog) and their locations.

The file is Root|Chain > SubChains > SubChain > Stores > Store, with tags matched on their local
name in any case (Shufersal writes STORE, the others Store). A Store has StoreID, StoreType,
StoreName, Address, City (a CBS settlement code, sometimes empty) and ZIPCode.

A physical store is geocoded (through geo.service) when it has no location or its address
changed, unless its location was set by hand or the same address failed in the last 24 hours.
Addresses never go into a log line.
"""

import logging
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from xml.etree.ElementTree import Element

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.catalog import service as catalog_service
from app.modules.catalog.service import StoreRecord, StoreState
from app.modules.geo.service import Geocoder, GeoPoint
from app.modules.ingestion.decode import child_fields as _fields
from app.modules.ingestion.decode import local_name

logger = logging.getLogger("app.ingestion")

# At most this many geocoder requests for one file. The rest wait for the next run.
MAX_GEOCODES_PER_FILE = 1000
# An address that found nothing is not tried again for this long.
RETRY_FAILED_AFTER = timedelta(hours=24)

_DIGITS = re.compile(r"[0-9]+")
# store_type is a smallint.
MAX_STORE_TYPE = 32767


def _record(element: Element, sub_chain_code: str | None) -> StoreRecord | None:
    """None for a store with no numeric StoreID or no StoreName."""
    fields = _fields(element)
    code = fields.get("storeid", "")
    name = fields.get("storename", "")
    if not _DIGITS.fullmatch(code) or not name:
        return None
    store_type = fields.get("storetype", "")
    return StoreRecord(
        gov_store_code=code.lstrip("0") or "0",
        sub_chain_code=fields.get("subchainid") or sub_chain_code,
        name=name,
        address=fields.get("address", ""),
        city_code=fields.get("city") or None,
        zip_code=fields.get("zipcode") or None,
        store_type=(
            int(store_type)
            if _DIGITS.fullmatch(store_type) and int(store_type) <= MAX_STORE_TYPE
            else None
        ),
    )


def parse_stores(root: Element) -> tuple[list[StoreRecord], int]:
    """The stores in the file, in file order, and how many Store elements were skipped."""
    records: list[StoreRecord] = []
    skipped = 0
    stack: list[tuple[Element, str | None]] = [(root, None)]
    while stack:
        element, sub_chain_code = stack.pop()
        tag = local_name(element.tag).lower() if isinstance(element.tag, str) else ""
        if tag == "subchain":
            sub_chain_code = _fields(element).get("subchainid") or sub_chain_code
        if tag == "store":
            record = _record(element, sub_chain_code)
            if record is None:
                skipped += 1
            else:
                records.append(record)
            continue
        stack.extend((child, sub_chain_code) for child in reversed(element))
    return records, skipped


def needs_geocode(state: StoreState, query: str, now: datetime) -> bool:
    """Whether a physical store is sent to the geocoder with this query."""
    if state.location_source == "manual":
        return False
    same_query = query == state.geocoded_query
    failed_at = state.geocode_attempted_at
    if failed_at is not None and same_query and now - failed_at < RETRY_FAILED_AFTER:
        return False
    # The last attempt for this query succeeded, so the location is still good.
    return not (state.has_location and same_query and failed_at is None)


def _locate(geocoder: Geocoder, query: str) -> tuple[GeoPoint | None, bool]:
    """(point, unavailable). An unavailable geocoder counts as nothing found for this store:
    the file does not fail for it."""
    try:
        return geocoder.locate(query), False
    except AppError as exc:
        if exc.status != 503:
            raise
        return None, True


def _utcnow() -> datetime:
    return datetime.now(UTC)


def stores_handler(
    geocoder: Geocoder | None,
    now: Callable[[], datetime] = _utcnow,
    max_geocodes: int = MAX_GEOCODES_PER_FILE,
) -> Callable[[Session, uuid.UUID, Element], int]:
    """The handler of Stores files. With no geocoder, stores are saved and none is geocoded."""

    def handle(session: Session, chain_id: uuid.UUID, root: Element) -> int:
        records, skipped = parse_stores(root)
        at = now()
        requests = found = deferred = unavailable = 0
        for record in records:
            state = catalog_service.upsert_store(session, chain_id, record, at)
            if record.online or geocoder is None:
                continue
            query = catalog_service.store_geocode_query(record)
            if query is None or not needs_geocode(state, query, at):
                continue
            # After the cap, or once the geocoder was unavailable, the rest wait for the next run.
            if requests >= max_geocodes or unavailable:
                deferred += 1
                continue
            requests += 1
            point, down = _locate(geocoder, query)
            unavailable += down
            if point is not None:
                found += 1
            catalog_service.set_store_geocode_result(
                session, state.id, query, (point.lat, point.lng) if point else None, at
            )
        log = logger.warning if skipped or unavailable else logger.info
        log(
            "ingestion_stores",
            extra={
                "stores": len(records),
                "skipped": skipped,
                "geocode_requests": requests,
                "geocode_found": found,
                "geocode_deferred": deferred,
                "geocode_unavailable": unavailable,
            },
        )
        return len(records)

    return handle
