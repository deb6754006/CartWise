"""matching: business logic. Other modules use matching data only through this file.

Every alias of a product, from an official file or a receipt line, is matched here: match() for
one alias, match_barcodes() for a whole price file. Only matching creates aliases, and it writes
them only through catalog.service, which owns product_aliases (and is the only one to create
products).

Story 4.1 matches by barcode only: an alias whose valid barcode has a product is matched to it
with certainty, and nothing is asked of the user. Anything else is unmatched for now; matching by
text (and proposing new products) is Story 4.2's.
"""

import logging
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.modules.catalog import service as catalog_service

logger = logging.getLogger("app.matching")

# final and disputed are an existing alias's state, returned as it is stored: settled by votes or
# by an operator (Story 4.3), and not changed by a barcode.
MatchState = Literal[
    "certain", "uncertain", "final", "disputed", "new_product_proposal", "unmatched"
]
MatchSource = Literal["official_file", "receipt"]


@dataclass(frozen=True, slots=True)
class MatchContext:
    """Where the alias was seen. Not used by barcode matching: it is for matching by text
    (Story 4.2), such as a price to test a candidate against."""

    source: MatchSource
    unit_price_agorot: int | None = None


@dataclass(frozen=True, slots=True)
class MatchResult:
    """The outcome of matching one alias.

    state is the alias's: final or disputed are returned as stored, with the product they point
    to, even when the barcode now has another product. product_id may be None (unmatched, and in
    later stories other states too): callers use it only when it is not None. candidates is empty
    in Story 4.1."""

    state: MatchState
    product_id: uuid.UUID | None
    alias_id: uuid.UUID | None
    confidence: float | None
    candidates: tuple[uuid.UUID, ...] = ()


UNMATCHED = MatchResult(state="unmatched", product_id=None, alias_id=None, confidence=None)


def _log(result: MatchResult, context: MatchContext | None, had_barcode: bool) -> MatchResult:
    # No alias text: it may come from a user's receipt.
    logger.info(
        "matching_match",
        extra={
            "state": result.state,
            "source": context.source if context is not None else None,
            "had_barcode": had_barcode,
        },
    )
    return result


def match(
    session: Session,
    alias_text: str,
    chain_id: uuid.UUID,
    barcode: str | None = None,
    context: MatchContext | None = None,
    now: datetime | None = None,
) -> MatchResult:
    """Match a chain's alias of a product. A valid barcode that has a product is a certain match:
    the alias is saved (or moved to that product when it was certain for another), unless it is
    final or disputed, which is returned as it is. Anything else is unmatched, and nothing is
    written. Does not commit."""
    had_barcode = bool(barcode and barcode.strip())
    code = catalog_service.valid_barcode(barcode) if barcode is not None else None
    text = catalog_service.clean_alias_text(alias_text)
    if code is None or text is None:
        return _log(UNMATCHED, context, had_barcode)
    product_id = catalog_service.product_ids_by_barcode(session, [code]).get(code)
    if product_id is None:
        return _log(UNMATCHED, context, had_barcode)
    alias = catalog_service.upsert_certain_alias(
        session, chain_id, text, code, product_id, now=now or datetime.now(UTC)
    )
    result = MatchResult(
        state=alias.state,
        product_id=alias.product_id,
        alias_id=alias.id,
        confidence=float(alias.confidence) if alias.confidence is not None else None,
    )
    return _log(result, context, had_barcode)


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
