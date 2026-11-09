"""matching: business logic. Other modules use matching data only through this file.

Every alias of a product, from an official file or a receipt line, is matched here: match() for
one alias, match_barcodes() for a whole price file's barcodes, and match_file_items() for its
items with no barcode. Only matching creates aliases, and it writes them only through
catalog.service, which owns product_aliases (and is the only one to create products).

match() tries, in order:
1. The barcode (Story 4.1): a valid barcode that has a product is a certain match.
2. Memory: an existing final or disputed alias of the same key is returned as it is.
3. The text (Story 4.2): candidates by trigram similarity, each scored by its name, pack size,
   unit and price; certain above a threshold, uncertain below it, and a new product proposed
   when nothing is near.
"""

import logging
import re
import uuid
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.catalog import service as catalog_service
from app.modules.catalog.models import PackUnit
from app.modules.catalog.service import AliasRef, ProductCandidate
from app.modules.matching import repository
from app.modules.matching.models import MAX_KEPT_CANDIDATES
from app.modules.pricing import service as pricing_service

logger = logging.getLogger("app.matching")

# final and disputed are an existing alias's state, returned as it is stored: settled by votes or
# by an operator (Story 4.3), and not changed by matching.
MatchState = Literal[
    "certain", "uncertain", "final", "disputed", "new_product_proposal", "unmatched"
]
MatchSource = Literal["official_file", "receipt"]
MatchPath = Literal["barcode", "memory", "text"]
Decision = Literal["certain", "uncertain", "new_product_proposal"]

_SETTLED = ("final", "disputed")


@dataclass(frozen=True, slots=True)
class MatchContext:
    """Where the alias was seen. unit_price_agorot, when known, tests each candidate's price
    against the median of its current regular prices. is_weighted, pack_size and pack_unit are
    the item's, from an official file: used only for a product proposed for it (pack_size and
    pack_unit together, or else the pack written in the text), never in scoring."""

    source: MatchSource
    unit_price_agorot: int | None = None
    is_weighted: bool = False
    pack_size: Decimal | None = None
    pack_unit: PackUnit | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    """A product an alias may be, with its score (0 to 1)."""

    product_id: uuid.UUID
    score: float


@dataclass(frozen=True, slots=True)
class MatchResult:
    """The outcome of matching one alias.

    state is the alias's: final or disputed are returned as stored, with the product they point
    to. new_product_proposal points to the product proposed for the alias. product_id may be None
    (unmatched, and in later stories disputed): callers use it only when it is not None.
    candidates are the best first, with scores rounded to 3 places: up to 3 for uncertain, the
    chosen one for certain by text, and none otherwise."""

    state: MatchState
    product_id: uuid.UUID | None
    alias_id: uuid.UUID | None
    confidence: float | None
    candidates: tuple[Candidate, ...] = ()


UNMATCHED = MatchResult(state="unmatched", product_id=None, alias_id=None, confidence=None)


@dataclass(frozen=True, slots=True)
class Thresholds:
    certain: float
    min_gap: float
    new_product_below: float


def thresholds() -> Thresholds:
    """From Settings: MATCH_CERTAIN_THRESHOLD, MATCH_MIN_GAP and MATCH_NEW_PRODUCT_BELOW."""
    settings = get_settings()
    return Thresholds(
        settings.MATCH_CERTAIN_THRESHOLD,
        settings.MATCH_MIN_GAP,
        settings.MATCH_NEW_PRODUCT_BELOW,
    )


# --- pack size and unit ---

# Longest first, so that a shorter word is tried only when the longer one is not there. Matched
# on text after normalize_he, so geresh and gershayim are gone: מ"ל is מל, ק"ג is קג, יח' is יח.
_UNIT_WORDS: tuple[tuple[str, PackUnit], ...] = (
    ("מיליליטר", "ml"),
    ("ליטרים", "l"),
    ("ליטר", "l"),
    ("מל", "ml"),
    ("ל", "l"),
    ("קילוגרם", "kg"),
    ("קילו", "kg"),
    ("קג", "kg"),
    ("גרם", "g"),
    ("גר", "g"),
    ("ג", "g"),
    ("יחידות", "unit"),
    ("יח", "unit"),
)
_UNITS: dict[str, PackUnit] = dict(_UNIT_WORDS)
# A number (not the end of a longer one), maybe spaces, then a unit with no letter after it.
_PACK = re.compile(
    r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*("
    + "|".join(word for word, _ in _UNIT_WORDS)
    + r")(?![^\W\d_])"
)
# A comma followed by exactly three digits separates thousands (1,000 גרם); any other comma is a
# decimal point (1,5 ליטר).
_THOUSANDS = re.compile(r",(?=\d{3}$)")


def parse_pack(text: str) -> tuple[Decimal | None, PackUnit | None]:
    """The pack size and unit written in a name (after normalize_he), such as 1.5ל, 750 מל,
    80 גרם, 1 קג or 6 יח: the last one when there are several, and (None, None) when there is
    none. Does not change normalize_he."""
    found: tuple[Decimal | None, PackUnit | None] = (None, None)
    for number, word in _PACK.findall(text):
        try:
            size = Decimal(_THOUSANDS.sub("", number).replace(",", "."))
        except InvalidOperation:  # pragma: no cover - the pattern only takes numbers
            continue
        if size > 0:
            found = (size, _UNITS[word])
    return found


_DIMENSION: dict[PackUnit, str] = {
    "g": "mass",
    "kg": "mass",
    "ml": "volume",
    "l": "volume",
    "unit": "count",
}
# To grams, millilitres or units.
_TO_BASE: dict[PackUnit, Decimal] = {
    "g": Decimal(1),
    "kg": Decimal(1000),
    "ml": Decimal(1),
    "l": Decimal(1000),
    "unit": Decimal(1),
}
SIZE_TOLERANCE = Decimal("0.02")
PRICE_TOLERANCE = 0.5


# --- text similarity ---

_WORD = re.compile(r"[^\W_]+")


def _trigrams(text: str) -> set[str]:
    # As pg_trgm: each word (a run of letters and digits), padded with two spaces before it and
    # one after it.
    grams: set[str] = set()
    for word in _WORD.findall(text.lower()):
        padded = f"  {word} "
        grams.update(padded[i : i + 3] for i in range(len(padded) - 2))
    return grams


def trigram_similarity(a: str, b: str) -> float:
    """As pg_trgm's similarity(a, b): the trigrams both share, over all the trigrams of both."""
    first, second = _trigrams(a), _trigrams(b)
    if not first or not second:
        return 0.0
    shared = len(first & second)
    return shared / (len(first) + len(second) - shared)


def _without_pack(text: str) -> str:
    stripped = " ".join(_PACK.sub(" ", text).split())
    return stripped or text


def text_similarity(alias_norm: str, name_norm: str) -> float:
    """The trigram similarity of the two names, with their pack sizes left out: those are scored
    on their own, by value (250ג and 250 גרם are the same size, though their trigrams differ)."""
    return trigram_similarity(_without_pack(alias_norm), _without_pack(name_norm))


# --- scoring ---

WEIGHT_TEXT = 0.45
WEIGHT_SIZE = 0.20
WEIGHT_UNIT = 0.10
WEIGHT_PRICE = 0.05
# The brand (0.20) is not scored until products have brands.


def _product_pack(product: ProductCandidate) -> tuple[Decimal | None, PackUnit | None]:
    if product.pack_size is not None and product.pack_unit is not None:
        return product.pack_size, product.pack_unit
    # Products from the price files mostly have no pack size, but their name often has it.
    return parse_pack(product.name_norm)


def _score(
    alias_norm: str,
    alias_pack: tuple[Decimal | None, PackUnit | None],
    product: ProductCandidate,
    unit_price_agorot: int | None,
    median: int | None,
) -> float:
    # Σ wᵢ·fᵢ / Σ wᵢ over the features that count. Size and unit count when the alias has them:
    # a product with none scores 0 on them (a generic "חלב" is not "חלב 1ל"). With no size on
    # the alias, they are left out. The price counts when both the price and a median are known.
    features: list[tuple[float, float]] = [
        (WEIGHT_TEXT, text_similarity(alias_norm, product.name_norm))
    ]
    size, unit = alias_pack
    product_size, product_unit = _product_pack(product)
    if size is not None and unit is not None:
        same_dimension = product_unit is not None and _DIMENSION[unit] == _DIMENSION[product_unit]
        same_size = False
        if same_dimension and product_size is not None and product_unit is not None:
            mine, theirs = size * _TO_BASE[unit], product_size * _TO_BASE[product_unit]
            same_size = abs(mine - theirs) <= SIZE_TOLERANCE * theirs
        features.append((WEIGHT_SIZE, 1.0 if same_size else 0.0))
        features.append((WEIGHT_UNIT, 1.0 if same_dimension else 0.0))
    if unit_price_agorot is not None and median is not None and median > 0:
        sane = abs(unit_price_agorot - median) <= PRICE_TOLERANCE * median
        features.append((WEIGHT_PRICE, 1.0 if sane else 0.0))
    score = sum(w * f for w, f in features) / sum(w for w, _ in features)
    return min(1.0, max(0.0, score))


def score_candidates(
    alias_norm: str,
    products: Sequence[ProductCandidate],
    unit_price_agorot: int | None = None,
    medians: Mapping[uuid.UUID, int] | None = None,
) -> list[Candidate]:
    """Each product scored as the alias's (alias_norm is from normalize_he), the best first, ties
    by id. Pure: reads and writes nothing. medians is the median regular price of each product,
    for unit_price_agorot to be tested against. Scores are not rounded."""
    alias_pack = parse_pack(alias_norm)
    known = medians or {}
    scored = [
        Candidate(
            product.id,
            _score(alias_norm, alias_pack, product, unit_price_agorot, known.get(product.id)),
        )
        for product in products
    ]
    return sorted(scored, key=lambda c: (-c.score, c.product_id))


def score_gap(scored: Sequence[Candidate]) -> float:
    """How far the best leads the second (0 when there is no second): scored is the best first."""
    if not scored:
        return 0.0
    second = scored[1].score if len(scored) > 1 else 0.0
    return scored[0].score - second


def decide(
    scored: Sequence[Candidate],
    limits: Thresholds,
    proposed: Collection[uuid.UUID] = frozenset(),
) -> Decision:
    """certain: the best scores at least limits.certain, and leads the second by at least
    limits.min_gap, and is not a proposed product (one nobody approved is uncertain at most).
    new_product_proposal: none scores at least limits.new_product_below. uncertain: anything
    else. scored is the best first, not rounded; proposed are the ids of proposed products."""
    if not scored or scored[0].score < limits.new_product_below:
        return "new_product_proposal"
    if (
        scored[0].score >= limits.certain
        and score_gap(scored) >= limits.min_gap
        and scored[0].product_id not in proposed
    ):
        return "certain"
    return "uncertain"


def proposed_ids(products: Iterable[ProductCandidate]) -> frozenset[uuid.UUID]:
    """The proposed products among these candidates."""
    return frozenset(p.id for p in products if p.status == "proposed")


def _stored(score: float) -> Decimal:
    return Decimal(str(round(score, 3)))


def _rounded(candidate: Candidate) -> Candidate:
    return Candidate(candidate.product_id, round(candidate.score, 3))


# --- match ---


def _log(
    result: MatchResult,
    context: MatchContext | None,
    had_barcode: bool,
    path: MatchPath | None = None,
    score: float | None = None,
    gap: float | None = None,
) -> MatchResult:
    # No alias text: it may come from a user's receipt.
    logger.info(
        "matching_match",
        extra={
            "state": result.state,
            "source": context.source if context is not None else None,
            "had_barcode": had_barcode,
            "path": path,
            "score": round(score, 3) if score is not None else None,
            "gap": round(gap, 3) if gap is not None else None,
        },
    )
    return result


def _as_stored(alias: AliasRef, candidates: tuple[Candidate, ...] = ()) -> MatchResult:
    return MatchResult(
        state=alias.state,
        product_id=alias.product_id,
        alias_id=alias.id,
        confidence=float(alias.confidence) if alias.confidence is not None else None,
        candidates=candidates,
    )


def match(
    session: Session,
    alias_text: str,
    chain_id: uuid.UUID,
    barcode: str | None = None,
    context: MatchContext | None = None,
    now: datetime | None = None,
) -> MatchResult:
    """Match a chain's alias of a product, and save the alias, with the input's barcode when it
    is valid (and with none otherwise):
    1. A valid barcode that has a product: certain (an alias certain for another product moves
       to it).
    2. Otherwise, an existing final or disputed alias of the same key, returned as it is.
    3. Otherwise by text: certain, uncertain (its top 3 candidates kept) or a new product
       proposed, by the thresholds in Settings.
    A final or disputed alias is never changed. A text that is empty after normalizing, or has
    no letter or digit to match by, is unmatched, and nothing is written. A proposed product is
    never a certain match, and an alias proposed before reuses its product. Does not commit."""
    had_barcode = bool(barcode and barcode.strip())
    text = catalog_service.clean_alias_text(alias_text)
    if text is None:
        return _log(UNMATCHED, context, had_barcode)
    when = now or datetime.now(UTC)
    code = catalog_service.valid_barcode(barcode) if barcode is not None else None
    if code is not None:
        product_id = catalog_service.product_ids_by_barcode(session, [code]).get(code)
        if product_id is not None:
            alias = catalog_service.upsert_certain_alias(
                session, chain_id, text, code, product_id, now=when
            )
            # A final or disputed alias is returned as it is: from memory, not by the barcode.
            path: MatchPath = "memory" if alias.state in _SETTLED else "barcode"
            return _log(_as_stored(alias), context, had_barcode, path)
    existing = catalog_service.alias_by_key(session, chain_id, text, code)
    if existing is not None and existing.state in _SETTLED:
        return _log(_as_stored(existing), context, had_barcode, "memory")
    if not _trigrams(catalog_service.normalize_he(text)):
        # No letter or digit (such as "***"): nothing to match by, and nothing to propose.
        return _log(UNMATCHED, context, had_barcode)
    return _match_text(session, chain_id, text, code, existing, context, when, had_barcode)


def _proposed_before(session: Session, existing: AliasRef | None) -> uuid.UUID | None:
    """The product proposed for this alias before, if it still is one: proposed again, it is
    reused rather than left behind for a new one."""
    if existing is None or existing.product_id is None:
        return None
    statuses = catalog_service.product_statuses(session, [existing.product_id])
    return existing.product_id if statuses.get(existing.product_id) == "proposed" else None


def _match_text(
    session: Session,
    chain_id: uuid.UUID,
    text: str,
    code: str | None,
    existing: AliasRef | None,
    context: MatchContext | None,
    now: datetime,
    had_barcode: bool,
) -> MatchResult:
    norm = catalog_service.normalize_he(text)
    products = catalog_service.product_candidates(session, norm)
    price = context.unit_price_agorot if context is not None else None
    medians = (
        pricing_service.median_prices(session, [p.id for p in products])
        if price is not None and products
        else {}
    )
    scored = score_candidates(norm, products, price, medians)
    decision = decide(scored, thresholds(), proposed_ids(products))
    best = scored[0].score if scored else None
    gap = score_gap(scored) if scored else None

    if decision == "new_product_proposal":
        proposed = _proposed_before(session, existing)
        if proposed is None:
            size, unit = parse_pack(norm)
            if context is not None and context.pack_size and context.pack_unit:
                size, unit = context.pack_size, context.pack_unit
            proposed = catalog_service.propose_product(
                session,
                text,
                size,
                unit,
                barcode=code,
                now=now,
                is_weighted=context.is_weighted if context is not None else False,
            )
        alias = catalog_service.upsert_alias(
            session, chain_id, text, code, "uncertain", proposed, None, now=now
        )
        if alias.state in _SETTLED:  # settled meanwhile, by another transaction
            return _log(_as_stored(alias), context, had_barcode, "memory")
        repository.replace_candidates(session, alias.id, [], now)
        result = MatchResult("new_product_proposal", alias.product_id, alias.id, None, ())
        return _log(result, context, had_barcode, "text", best, gap)

    top = scored[0]
    alias = catalog_service.upsert_alias(
        session, chain_id, text, code, decision, top.product_id, _stored(top.score), now=now
    )
    if alias.state in _SETTLED:
        return _log(_as_stored(alias), context, had_barcode, "memory")
    if alias.state == "certain":
        # Certain now, or certain before for this same product: it does not go down.
        repository.replace_candidates(session, alias.id, [], now)
        result = _as_stored(alias, (_rounded(top),))
    else:
        kept = [_rounded(c) for c in scored[:MAX_KEPT_CANDIDATES]]
        repository.replace_candidates(
            session, alias.id, [(c.product_id, _stored(c.score)) for c in kept], now
        )
        result = _as_stored(alias, tuple(kept))
    return _log(result, context, had_barcode, "text", best, gap)


@dataclass(frozen=True, slots=True)
class FileItem:
    """An item of an official file with no barcode. unit_price_agorot is its price when it is per
    unit (None otherwise); is_weighted and the pack go to a product proposed for it."""

    alias_text: str
    unit_price_agorot: int | None = None
    is_weighted: bool = False
    pack_size: Decimal | None = None
    pack_unit: PackUnit | None = None


_FILE_ITEM_COUNTS = (
    "items",
    "reused",
    "matched",
    "certain",
    "uncertain",
    "proposed",
    "final",
    "disputed",
    "unmatched",
)


def match_file_items(
    session: Session,
    chain_id: uuid.UUID,
    items: Sequence[FileItem],
    now: datetime | None = None,
) -> list[uuid.UUID | None]:
    """Matching for the items of an official file with no barcode (Story 3.6): the product of each
    item, in the same order, or None.

    An item whose text the chain already has an alias of, with no barcode, pointing to a product
    (in any state, and not merged into another), gets that product: it is not scored again, and
    nothing is written. So does a text seen before in this call. Every other item goes through
    match() with no barcode and the item in the context. A text that clean_alias_text rejects gets
    None. Does not commit."""
    norms = [catalog_service.alias_norm(item.alias_text) for item in items]
    known: dict[str, uuid.UUID] = catalog_service.alias_products_by_norm(
        session, chain_id, (n for n in norms if n is not None)
    )
    counts: Counter[str] = Counter()
    result: list[uuid.UUID | None] = []
    for item, norm in zip(items, norms, strict=True):
        counts["items"] += 1
        if norm is None:
            counts["unmatched"] += 1
            result.append(None)
            continue
        if norm in known:
            counts["reused"] += 1
            result.append(known[norm])
            continue
        context = MatchContext(
            source="official_file",
            unit_price_agorot=item.unit_price_agorot,
            is_weighted=item.is_weighted,
            pack_size=item.pack_size,
            pack_unit=item.pack_unit,
        )
        outcome = match(session, item.alias_text, chain_id, None, context, now)
        if outcome.state == "new_product_proposal":
            counts["proposed"] += 1
        elif outcome.state != "unmatched":
            counts[outcome.state] += 1
        if outcome.product_id is None:
            counts["unmatched"] += 1
        else:
            counts["matched"] += 1
            known[norm] = outcome.product_id
        result.append(outcome.product_id)
    # Counts only: no alias text.
    logger.info("matching_file_items", extra={name: counts[name] for name in _FILE_ITEM_COUNTS})
    return result


def match_barcodes(
    session: Session,
    chain_id: uuid.UUID,
    items: Iterable[tuple[str, str | None]],
    now: datetime | None = None,
    product_ids: Mapping[str, uuid.UUID] | None = None,
) -> int:
    """Bulk barcode matching, for ingestion: a certain alias for each (alias_text, barcode) whose
    valid barcode has a product, created or moved to that product as in match() (a final or
    disputed alias is not changed). product_ids, when given, is the product of each barcode, and
    the barcodes are not looked up again. Returns how many aliases were created. Does not
    commit."""
    counts: Counter[str] = Counter()
    wanted: list[tuple[str, str]] = []
    for alias_text, barcode in items:
        counts["items"] += 1
        code = catalog_service.valid_barcode(barcode) if barcode is not None else None
        if code is None:
            counts["invalid_barcode"] += 1
        else:
            wanted.append((alias_text, code))
    found: Mapping[str, uuid.UUID] = {}
    if wanted:
        found = (
            product_ids
            if product_ids is not None
            else catalog_service.product_ids_by_barcode(session, (code for _, code in wanted))
        )
    matched = [(text, code, found[code]) for text, code in wanted if code in found]
    counts["no_product"] = len(wanted) - len(matched)
    new = (
        catalog_service.ensure_certain_aliases(session, chain_id, matched, now=now)
        if matched
        else 0
    )
    # Counts only: no alias text.
    logger.info(
        "matching_match_bulk",
        extra={
            "items": counts["items"],
            "invalid_barcode": counts["invalid_barcode"],
            "no_product": counts["no_product"],
            "aliases_new": new,
        },
    )
    return new
