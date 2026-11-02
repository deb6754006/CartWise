"""catalog: business logic. Other modules use catalog data only through this file."""

import unicodedata
import uuid
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.catalog import repository

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
