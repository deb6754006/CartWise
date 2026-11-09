"""catalog: business logic. Other modules use catalog data only through this file."""

import csv
import math
import re
import unicodedata
import uuid
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.modules.catalog import repository
from app.modules.catalog.models import (
    AliasState,
    LocationSource,
    PackUnit,
    ProductStatus,
    StoreStatus,
)

# Search needs this many characters, after normalizing.
MIN_BRAND_SEARCH_LENGTH = 2
MAX_BRAND_SEARCH_RESULTS = 20

# Geresh, gershayim and quotation marks, as typed on any keyboard or pasted from any source.
_QUOTES = frozenset("'`\u00b4\u05f3\u2018\u2019\u201a\u201b\"\u05f4\u201c\u201d\u201e\u201f")
# Hyphen, maqaf and dashes: a name written with one is found when typed with a space.
_HYPHENS = frozenset("-\u05be\u2010\u2011\u2012\u2013\u2014\u2015")


@dataclass(frozen=True, slots=True)
class ChainRef:
    id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class ClubRef:
    id: uuid.UUID
    name: str
    chain_id: uuid.UUID
    chain_name: str


@dataclass(frozen=True, slots=True)
class BrandRef:
    id: uuid.UUID
    name: str


# StoreType of an online store, in the chains' Stores files. Any other type is a physical store.
ONLINE_STORE_TYPE = 2

# From the Population Authority's "settlements in Israel" dataset on data.gov.il (open licence):
# code,name for each CBS settlement code. See deploy/README.md.
SETTLEMENTS_CSV = Path(__file__).resolve().parent / "data" / "settlements.csv"


@dataclass(frozen=True, slots=True)
class StoreRecord:
    """One store as read from a chain's Stores file."""

    gov_store_code: str
    sub_chain_code: str | None
    name: str
    address: str
    city_code: str | None
    zip_code: str | None
    store_type: int | None

    @property
    def online(self) -> bool:
        return self.store_type == ONLINE_STORE_TYPE


@dataclass(frozen=True, slots=True)
class StoreState:
    """What decides whether a store is geocoded."""

    id: uuid.UUID
    status: StoreStatus
    has_location: bool
    location_source: LocationSource | None
    geocoded_query: str | None
    geocode_attempted_at: datetime | None


@dataclass(frozen=True, slots=True)
class StoreRef:
    id: uuid.UUID
    chain_id: uuid.UUID
    chain_name: str
    gov_store_code: str
    name: str
    address: str
    city_code: str | None


def _is_hebrew_mark(char: str) -> bool:
    # By category, since this range also has punctuation: a maqaf is not niqqud.
    return "\u0591" <= char <= "\u05c7" and unicodedata.category(char) == "Mn"


def normalize_he(text: str) -> str:
    """The searchable form of a Hebrew name: the one place text is normalized for search.

    Removes niqqud, geresh, gershayim, quotation marks and invisible format characters (such as
    direction marks in pasted text), turns hyphens into spaces, collapses whitespace and lowercases
    Latin letters. Spelling variants and abbreviations (NFR-21) will be added here, and only here.
    """
    # NFC first: it decomposes the presentation forms, so their niqqud is removed as well.
    kept = "".join(
        " " if char in _HYPHENS else char
        for char in unicodedata.normalize("NFC", text)
        if char not in _QUOTES and not _is_hebrew_mark(char) and unicodedata.category(char) != "Cf"
    )
    return unicodedata.normalize("NFC", " ".join(kept.split()).lower())


def list_chains(session: Session) -> list[ChainRef]:
    """All chains, sorted by name."""
    return [ChainRef(*row) for row in repository.list_chains(session)]


def chains_by_gov_codes(session: Session, gov_chain_codes: Collection[str]) -> list[ChainRef]:
    """The chains that exist among these government chain codes."""
    return [ChainRef(*row) for row in repository.chains_by_gov_codes(session, gov_chain_codes)]


def list_clubs(session: Session) -> list[ClubRef]:
    """All clubs, sorted by chain name and then club name."""
    return [ClubRef(*row) for row in repository.list_clubs(session)]


def existing_club_ids(session: Session, ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """The subset of ids that are real clubs."""
    return repository.existing_club_ids(session, ids)


def ensure_chain_with_club(session: Session, chain_name: str, club_name: str) -> uuid.UUID:
    """Make sure the chain and its club exist. Idempotent. Returns the club id.

    Does not commit: the caller owns the transaction.
    """
    chain_id = repository.ensure_chain(session, unicodedata.normalize("NFC", chain_name))
    return repository.ensure_club(session, chain_id, unicodedata.normalize("NFC", club_name))


def ensure_chain(session: Session, gov_chain_code: str, name: str) -> uuid.UUID:
    """Make sure the chain with this government chain code exists. Idempotent. Returns its id.

    An existing chain keeps its name. Does not commit: the caller owns the transaction.
    """
    return repository.ensure_chain_by_code(
        session, gov_chain_code.strip(), unicodedata.normalize("NFC", name)
    )


def search_brands(session: Session, query: str) -> list[BrandRef]:
    """Up to 20 brands matching query anywhere in their name. Too short a query matches nothing."""
    normalized = normalize_he(query)
    # No name contains NUL, and Postgres rejects it in a parameter.
    if len(normalized) < MIN_BRAND_SEARCH_LENGTH or "\x00" in normalized:
        return []
    rows = repository.search_brands(session, normalized, MAX_BRAND_SEARCH_RESULTS)
    return [BrandRef(*row) for row in rows]


def brands_by_ids(session: Session, ids: Collection[uuid.UUID]) -> list[BrandRef]:
    """The brands with these ids, sorted by name. An unknown id is left out."""
    return [BrandRef(*row) for row in repository.brands_by_ids(session, ids)]


def existing_brand_ids(session: Session, ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """The subset of ids that are real brands."""
    return repository.existing_brand_ids(session, ids)


def ensure_brand(session: Session, name: str) -> uuid.UUID:
    """Make sure the brand exists. Idempotent. Returns its id.

    Does not commit: the caller owns the transaction.
    """
    return repository.ensure_brand(session, unicodedata.normalize("NFC", name), normalize_he(name))


def _clean(text: str) -> str:
    """NFC, with runs of whitespace collapsed to one space."""
    return " ".join(unicodedata.normalize("NFC", text).split())


@cache
def _settlements() -> dict[str, str]:
    with SETTLEMENTS_CSV.open(encoding="utf-8", newline="") as stream:
        return {row["code"].strip(): _clean(row["name"]) for row in csv.DictReader(stream)}


def settlement_name(code: str) -> str | None:
    """The name of the settlement with this CBS code, or None for an unknown code."""
    code = code.strip()
    if not code.isascii() or not code.isdigit():
        return None
    return _settlements().get(str(int(code)))


def store_geocode_query(record: StoreRecord) -> str | None:
    """'<Address>, <settlement name>' (or the address alone, when the settlement is unknown).

    None when there is no address: a settlement alone would place the store at its center.
    """
    address = _clean(record.address)
    if not address:
        return None
    city = _clean(record.city_code or "")
    name = city if city and not city.isdigit() else settlement_name(city) if city else None
    return _clean(f"{address}, {name}") if name else address


def _state(row: Any) -> StoreState:
    return StoreState(
        id=row.id,
        status=row.status,
        has_location=bool(row.has_location),
        location_source=row.location_source,
        geocoded_query=row.geocoded_query,
        geocode_attempted_at=row.geocode_attempted_at,
    )


def upsert_store(
    session: Session, chain_id: uuid.UUID, record: StoreRecord, now: datetime
) -> StoreState:
    """Create the store, or update its name and address. Returns its state after that.

    The location is not touched here. Does not commit: the caller owns the transaction.
    """
    code = record.gov_store_code.strip()
    name = _clean(record.name)
    after = repository.upsert_store(
        session,
        chain_id=chain_id,
        gov_store_code=code,
        sub_chain_code=record.sub_chain_code,
        name=name,
        name_norm=normalize_he(name),
        address=_clean(record.address),
        city_code=record.city_code,
        zip_code=record.zip_code,
        store_type=record.store_type,
        online=record.online,
        now=now,
    )
    return _state(after)


def set_store_geocode_result(
    session: Session,
    store_id: uuid.UUID,
    query: str,
    point: tuple[float, float] | None,
    now: datetime,
) -> None:
    """Record a geocoding attempt. point is (lat, lng), or None when nothing was found.

    Found: the store gets that location and is active. Not found: a location it already has is
    kept, and a store with none needs a location. A manual location is never changed.
    """
    if point is None:
        repository.set_store_geocode_failed(session, store_id, query, now)
    else:
        repository.set_store_geocoded(session, store_id, query, point[0], point[1], now)


def stores_needing_location(session: Session) -> list[StoreRef]:
    """Physical stores with no location: left out of comparisons until an operator sets one."""
    return [StoreRef(*row) for row in repository.stores_needing_location(session)]


# A rough box around Israel: a manual point outside it is a mistake, such as lat and lng swapped.
MANUAL_LAT_RANGE = (29.0, 33.5)
MANUAL_LNG_RANGE = (34.0, 36.0)


def _valid_coordinates(lat: float, lng: float) -> bool:
    return (
        math.isfinite(lat)
        and math.isfinite(lng)
        and MANUAL_LAT_RANGE[0] <= lat <= MANUAL_LAT_RANGE[1]
        and MANUAL_LNG_RANGE[0] <= lng <= MANUAL_LNG_RANGE[1]
    )


def set_store_location_manual(
    session: Session, store_id: uuid.UUID, lat: float, lng: float, now: datetime | None = None
) -> None:
    """Set a store's location by hand. It is never replaced by geocoding. Raises ValueError,
    changing nothing, for coordinates outside Israel (roughly), an unknown store or an online
    store. Does not commit."""
    if not _valid_coordinates(lat, lng):
        raise ValueError("coordinates out of range (outside Israel)")
    when = now if now is not None else datetime.now(UTC)
    outcome = repository.set_store_location_manual(session, store_id, lat, lng, when)
    if outcome == "missing":
        raise ValueError("no such store")
    if outcome == "online":
        raise ValueError("an online store has no location")


def comparable_store_ids(session: Session, chain_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    """The stores that take part in comparisons: active, with a location."""
    return repository.comparable_store_ids(session, chain_id)


def store_id_by_code(
    session: Session, chain_id: uuid.UUID, gov_store_code: str
) -> uuid.UUID | None:
    """The chain's store with this government store code (leading zeros dropped), or None."""
    code = gov_store_code.strip()
    if code.isascii() and code.isdigit():
        code = code.lstrip("0") or "0"
    return repository.store_id_by_code(session, chain_id, code)


def ensure_chain_club(session: Session, chain_id: uuid.UUID) -> uuid.UUID:
    """The chain's club, 'מועדון <chain name>', created if missing: one per chain. Returns its id.

    Does not commit: the caller owns the transaction.
    """
    name = unicodedata.normalize("NFC", f"מועדון {repository.chain_name(session, chain_id)}")
    return repository.ensure_club(session, chain_id, name)


@dataclass(frozen=True, slots=True)
class ProductRecord:
    """A product with a barcode, as read from a chain's price file."""

    barcode: str
    name: str
    pack_size: Decimal | None
    pack_unit: PackUnit | None
    is_weighted: bool


def ensure_products_by_barcode(
    session: Session, items: Iterable[ProductRecord], now: datetime | None = None
) -> dict[str, uuid.UUID]:
    """The product id of each item's barcode. A barcode with no product gets one, from the first
    item with it; an existing product is not changed (its first name stays).

    Barcodes are kept as they are, leading zeros included. Does not commit.
    """
    when = now if now is not None else datetime.now(UTC)
    first: dict[str, ProductRecord] = {}
    for item in items:
        first.setdefault(item.barcode, item)
    # Sorted, so two chains inserting the same barcodes at once take the locks in one order.
    barcodes = sorted(first)
    rows = []
    for barcode in barcodes:
        item = first[barcode]
        name = _clean(item.name)
        rows.append(
            {
                "id": new_id(),
                "barcode": barcode,
                "name": name,
                "name_norm": normalize_he(name),
                "pack_size": item.pack_size if item.pack_unit is not None else None,
                "pack_unit": item.pack_unit if item.pack_size is not None else None,
                "is_weighted": item.is_weighted,
                "status": "active",
                "created_at": when,
            }
        )
    repository.insert_products(session, rows)
    return repository.product_ids_by_barcode(session, barcodes)


def product_ids_by_barcode(session: Session, barcodes: Iterable[str]) -> dict[str, uuid.UUID]:
    """The id of the existing product of each barcode that has one. Creates nothing."""
    wanted: Sequence[str] = sorted(set(barcodes))
    return repository.product_ids_by_barcode(session, wanted)


_BARCODE = re.compile(r"[0-9]{8,14}")


def valid_barcode(code: str) -> str | None:
    """The barcode, when code is one: 8 to 14 digits, not all zeros, after trimming whitespace at
    its ends. Kept as it is otherwise: no zeros added or dropped, and no check digit test (about
    3% of the barcodes in real files fail it, and they are real products)."""
    text = code.strip()
    if not _BARCODE.fullmatch(text) or not text.strip("0"):
        # All zeros is a placeholder: it would merge unrelated items into one product.
        return None
    return text


# The confidence of an alias matched by its barcode.
BARCODE_CONFIDENCE = Decimal(1)


@dataclass(frozen=True, slots=True)
class AliasRef:
    id: uuid.UUID
    state: AliasState
    product_id: uuid.UUID | None
    confidence: Decimal | None


# Longer, alias_norm could exceed the size of a btree index row, and the insert would fail the
# whole transaction (a price file's prices included). No real product name comes near it.
MAX_ALIAS_NORM_LENGTH = 500


def clean_alias_text(text: str) -> str | None:
    """An alias as it is kept (NFC, whitespace collapsed), or None when nothing is left of it
    after normalizing, or when it is longer than MAX_ALIAS_NORM_LENGTH normalized."""
    # Postgres rejects NUL in text.
    cleaned = _clean(text.replace("\x00", " "))
    norm = normalize_he(cleaned)
    return cleaned if norm and len(norm) <= MAX_ALIAS_NORM_LENGTH else None


def upsert_certain_alias(
    session: Session,
    chain_id: uuid.UUID,
    alias_text: str,
    barcode: str,
    product_id: uuid.UUID,
    now: datetime | None = None,
) -> AliasRef:
    """The chain's alias of this text and barcode, certain for product_id (the product of the
    barcode): created, or moved to product_id when it is certain (or uncertain) for another. A
    final or disputed alias is not changed. alias_text must come from clean_alias_text.

    For matching only: catalog does not decide what an alias matches. Does not commit.
    """
    row = repository.upsert_certain_alias(
        session,
        chain_id=chain_id,
        alias_text=alias_text,
        alias_norm=normalize_he(alias_text),
        barcode=barcode,
        product_id=product_id,
        confidence=BARCODE_CONFIDENCE,
        now=now if now is not None else datetime.now(UTC),
    )
    return AliasRef(*row)


def ensure_certain_aliases(
    session: Session,
    chain_id: uuid.UUID,
    items: Iterable[tuple[str, str, uuid.UUID]],
    now: datetime | None = None,
) -> int:
    """Bulk: a certain alias for each (alias_text, barcode, product_id), created, or moved to
    product_id as in upsert_certain_alias (a final or disputed alias is not changed). A text that
    clean_alias_text rejects is skipped. Returns how many were created.

    For matching only. Does not commit.
    """
    when = now if now is not None else datetime.now(UTC)
    first: dict[tuple[str, str], dict[str, Any]] = {}
    for alias_text, barcode, product_id in items:
        text = clean_alias_text(alias_text)
        if text is None:
            continue
        norm = normalize_he(text)
        first.setdefault(
            (norm, barcode),
            {
                "id": new_id(),
                "chain_id": chain_id,
                "alias_text": text,
                "alias_norm": norm,
                "barcode": barcode,
                "product_id": product_id,
                "state": "certain",
                "confidence": BARCODE_CONFIDENCE,
                "created_at": when,
                "updated_at": when,
            },
        )
    # Sorted by key, so two runs inserting the same aliases at once take the locks in one order.
    return repository.upsert_certain_aliases(session, [first[key] for key in sorted(first)])


def alias_by_key(
    session: Session, chain_id: uuid.UUID, alias_text: str, barcode: str | None
) -> AliasRef | None:
    """The chain's alias of this text and barcode (None: no barcode), if there is one. alias_text
    must come from clean_alias_text."""
    row = repository.alias_by_key(session, chain_id, normalize_he(alias_text), barcode)
    return AliasRef(*row) if row is not None else None


def upsert_alias(
    session: Session,
    chain_id: uuid.UUID,
    alias_text: str,
    barcode: str | None,
    state: Literal["certain", "uncertain"],
    product_id: uuid.UUID,
    confidence: Decimal | None,
    now: datetime | None = None,
) -> AliasRef:
    """The chain's alias of this text and barcode (None: no barcode), created or set to this
    state, product and confidence. A final or disputed alias is not changed, and a certain alias
    for product_id does not go down to uncertain. alias_text must come from clean_alias_text.

    For matching only: catalog does not decide what an alias matches. Does not commit.
    """
    row = repository.upsert_alias(
        session,
        chain_id=chain_id,
        alias_text=alias_text,
        alias_norm=normalize_he(alias_text),
        barcode=barcode,
        state=state,
        product_id=product_id,
        confidence=confidence,
        now=now if now is not None else datetime.now(UTC),
    )
    return AliasRef(*row)


def propose_product(
    session: Session,
    name: str,
    pack_size: Decimal | None,
    pack_unit: PackUnit | None,
    barcode: str | None = None,
    now: datetime | None = None,
) -> uuid.UUID:
    """A new product, proposed (by matching, for an alias that matches none) until an operator
    approves it, with the alias's valid barcode (from valid_barcode) or none. Returns its id;
    when the barcode already has a product (created meanwhile), that product's id instead.
    Does not commit."""
    cleaned = _clean(name)
    has_pack = pack_size is not None and pack_unit is not None and pack_size > 0
    return repository.insert_product(
        session,
        {
            "id": new_id(),
            "barcode": barcode,
            "name": cleaned,
            "name_norm": normalize_he(cleaned),
            "pack_size": pack_size if has_pack else None,
            "pack_unit": pack_unit if has_pack else None,
            "is_weighted": False,
            "status": "proposed",
            "created_at": now if now is not None else datetime.now(UTC),
        },
    )


# Candidates by trigram similarity: low, so that a weak candidate is still scored (and a new
# product proposed only when nothing is near).
CANDIDATE_SIMILARITY_THRESHOLD = 0.2
MAX_CANDIDATES = 20


@dataclass(frozen=True, slots=True)
class ProductCandidate:
    """A product that may be an alias's, with the trigram similarity of its name_norm to the
    alias's alias_norm."""

    id: uuid.UUID
    name_norm: str
    pack_size: Decimal | None
    pack_unit: PackUnit | None
    status: ProductStatus
    similarity: float


def product_candidates(
    session: Session, alias_norm: str, limit: int = MAX_CANDIDATES
) -> list[ProductCandidate]:
    """Up to limit products (any status but merged_into, proposed included) whose name_norm is
    trigram-similar to alias_norm, most similar first. Uses the trigram index."""
    rows = repository.product_candidates(session, alias_norm, CANDIDATE_SIMILARITY_THRESHOLD, limit)
    return [ProductCandidate(*row) for row in rows]  # type: ignore[arg-type]


def product_statuses(
    session: Session, ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, ProductStatus]:
    """The status of each of these products that exists."""
    return repository.product_statuses(session, ids)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class AliasSample:
    id: uuid.UUID
    alias_norm: str
    product_id: uuid.UUID
    product_name_norm: str


def sample_certain_barcode_aliases(session: Session, limit: int, seed: str) -> list[AliasSample]:
    """Up to limit certain aliases with a barcode (whose product is known), picked by seed: the
    same seed picks the same ones. Reads only."""
    return [
        AliasSample(*row) for row in repository.sample_certain_barcode_aliases(session, limit, seed)
    ]
