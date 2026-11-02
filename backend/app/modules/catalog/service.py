"""catalog: business logic. Other modules use catalog data only through this file."""

import unicodedata
import uuid
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.catalog import repository


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
