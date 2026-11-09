"""The chain's memory of matches (Story 4.4), against Postgres. Every product and barcode here is
invented."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import make_engine
from app.modules.catalog import service as catalog_service
from app.modules.catalog.service import ProductRecord
from app.modules.matching import service as matching_service
from app.modules.matching.service import FileItem, MatchContext, MatchResult
from tests.integration.pg import alembic_config, create_database

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
RECEIPT = MatchContext("receipt")
TOMATOES = "עגבניות שרי"


@pytest.fixture(scope="module")
def memory_url(db_url: str) -> str:
    """A database of its own: these tests truncate and count rows."""
    url = create_database(db_url, "cw_match_memory")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(memory_url: str) -> Iterator[Engine]:
    eng = make_engine(memory_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE match_votes, match_candidates, product_aliases, promotion_products, "
                "promotions, price_observations, products, ingestion_alerts, ingestion_files, "
                "ingestion_runs, stores, user_clubs, user_brands, user_prefs, clubs, chains, "
                "devices, users"
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _chain(factory: sessionmaker[Session], code: str) -> uuid.UUID:
    with factory() as session:
        chain_id = catalog_service.ensure_chain(session, code, "רשת בדויה")
        session.commit()
    return chain_id


@pytest.fixture
def chain(factory: sessionmaker[Session]) -> uuid.UUID:
    return _chain(factory, "7290000000000")


@pytest.fixture
def other_chain(factory: sessionmaker[Session]) -> uuid.UUID:
    return _chain(factory, "7290000000002")


def _product(factory: sessionmaker[Session], name: str, barcode: str) -> uuid.UUID:
    with factory() as session:
        ids = catalog_service.ensure_products_by_barcode(
            session, [ProductRecord(barcode, name, None, None, False)], now=NOW
        )
        session.commit()
    return ids[barcode]


def _match(
    factory: sessionmaker[Session],
    alias: str,
    chain_id: uuid.UUID,
    barcode: str | None = None,
) -> MatchResult:
    with factory() as session:
        result = matching_service.match(session, alias, chain_id, barcode, RECEIPT, now=NOW)
        session.commit()
    return result


def _rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql), params)]


def _set_state(engine: Engine, alias_id: uuid.UUID | None, state: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE product_aliases SET state = :s WHERE id = :id"),
            {"s": state, "id": alias_id},
        )


def _final_alias(
    engine: Engine,
    factory: sessionmaker[Session],
    chain_id: uuid.UUID,
    alias: str,
    barcode: str,
) -> MatchResult:
    """An alias with a barcode, matched by it and then made final."""
    result = _match(factory, alias, chain_id, barcode)
    assert result.state == "certain"
    _set_state(engine, result.alias_id, "final")
    return result


def _match_logged(
    factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    alias: str,
    chain_id: uuid.UUID,
    barcode: str | None = None,
) -> tuple[MatchResult, Any]:
    caplog.clear()
    with caplog.at_level("INFO", logger="app.matching"):
        result = _match(factory, alias, chain_id, barcode)
    [record] = [r for r in caplog.records if r.getMessage() == "matching_match"]
    return result, record


# --- the matrix ---


def test_memory_in_the_chain(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tomatoes = _product(factory, "עגבניות שרי ארוז", "7290000000101")
    first = _final_alias(engine, factory, chain, TOMATOES, "7290000000101")
    result, record = _match_logged(factory, caplog, TOMATOES, chain)
    assert (result.state, result.product_id, result.confidence) == ("final", tomatoes, 1.0)
    assert result.needs_confirmation is False
    assert result.alias_id != first.alias_id
    assert (record.path, record.memory_scope, record.memory_ambiguous) == (
        "memory",
        "chain",
        False,
    )
    [alias] = _rows(
        engine, "SELECT * FROM product_aliases WHERE barcode IS NULL AND chain_id = :c", c=chain
    )
    assert (alias["id"], alias["state"], alias["product_id"], alias["confidence"]) == (
        result.alias_id,
        "final",
        tomatoes,
        Decimal(1),
    )
    # Seen again: its own key's final alias, from memory.
    again, record = _match_logged(factory, caplog, TOMATOES, chain)
    assert (again.state, again.alias_id) == ("final", result.alias_id)
    assert (record.path, record.memory_scope) == ("memory", "key")


def test_an_uncertain_alias_of_the_key_becomes_final(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    nuts = _product(factory, "שוקולד חלב אגוזים", "7290000000111")
    _product(factory, "שוקולד חלב שקדים", "7290000000112")
    before = _match(factory, "שוקולד חלב", chain)
    assert before.state == "uncertain"
    assert _rows(engine, "SELECT * FROM match_candidates")
    _final_alias(engine, factory, chain, "שוקולד חלב", "7290000000111")
    result = _match(factory, "שוקולד חלב", chain)
    assert (result.state, result.product_id, result.alias_id) == ("final", nuts, before.alias_id)
    assert _rows(engine, "SELECT * FROM match_candidates") == []


def test_another_chain_does_not_remember(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    other_chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _product(factory, "עגבניות שרי ארוז", "7290000000121")
    _final_alias(engine, factory, chain, TOMATOES, "7290000000121")
    result, record = _match_logged(factory, caplog, TOMATOES, other_chain)
    assert result.state != "final"
    assert (record.path, record.memory_ambiguous) == ("text", False)
    assert record.memory_scope is None


def test_ambiguous_memory_goes_by_the_text(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _product(factory, "עגבניות שרי אדומות", "7290000000131")
    _product(factory, "עגבניות שרי צהובות", "7290000000132")
    _final_alias(engine, factory, chain, TOMATOES, "7290000000131")
    _final_alias(engine, factory, chain, TOMATOES, "7290000000132")
    result, record = _match_logged(factory, caplog, TOMATOES, chain)
    assert result.state != "final"
    assert (record.path, record.memory_ambiguous) == ("text", True)


def test_the_barcode_wins(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _product(factory, "עגבניות שרי ארוז", "7290000000141")
    other = _product(factory, "מוצר אחר לגמרי", "7290000000142")
    _final_alias(engine, factory, chain, TOMATOES, "7290000000141")
    result, record = _match_logged(factory, caplog, TOMATOES, chain, "7290000000142")
    assert (result.state, result.product_id) == ("certain", other)
    assert result.needs_confirmation is False
    assert record.path == "barcode"


def test_a_certain_alias_is_not_memory(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _product(factory, "עגבניות שרי ארוז", "7290000000151")
    first = _match(factory, TOMATOES, chain, "7290000000151")
    assert first.state == "certain"
    result, record = _match_logged(factory, caplog, TOMATOES, chain)
    assert result.state != "final"
    assert (record.path, record.memory_ambiguous) == ("text", False)


def test_a_merged_product_is_not_memory(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    merged = _product(factory, "עגבניות שרי ארוז", "7290000000161")
    _final_alias(engine, factory, chain, TOMATOES, "7290000000161")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE products SET status = 'merged_into' WHERE id = :id"), {"id": merged}
        )
    result, record = _match_logged(factory, caplog, TOMATOES, chain)
    assert result.state != "final"
    assert result.product_id != merged
    assert (record.path, record.memory_ambiguous) == ("text", False)


@pytest.mark.parametrize(
    ("state", "needs"),
    [
        ("uncertain", True),
        ("new_product_proposal", True),
        ("certain", False),
        ("final", False),
        ("disputed", False),
        ("unmatched", False),
    ],
)
def test_needs_confirmation(state: Any, needs: bool) -> None:
    result = MatchResult(state, uuid.uuid4(), uuid.uuid4(), None)
    assert result.needs_confirmation is needs


def test_a_file_item_gets_the_chains_memory(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tomatoes = _product(factory, "עגבניות שרי ארוז", "7290000000171")
    _final_alias(engine, factory, chain, TOMATOES, "7290000000171")

    def no_match(*_a: Any, **_k: Any) -> MatchResult:
        raise AssertionError("match() was called")

    monkeypatch.setattr(matching_service, "match", no_match)
    with factory() as session:
        result = matching_service.match_file_items(session, chain, [FileItem(TOMATOES)], now=NOW)
        session.commit()
    assert result == [tomatoes]
    # Read only: no alias was written for it.
    [alias] = _rows(engine, "SELECT barcode FROM product_aliases")
    assert alias["barcode"] == "7290000000171"


def test_a_file_item_with_ambiguous_memory_keeps_its_own_alias(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    _product(factory, "עגבניות שרי אדומות", "7290000000181")
    _product(factory, "עגבניות שרי צהובות", "7290000000182")
    own = _match(factory, TOMATOES, chain)
    assert own.product_id is not None
    _final_alias(engine, factory, chain, TOMATOES, "7290000000181")
    _final_alias(engine, factory, chain, TOMATOES, "7290000000182")
    with factory() as session:
        found = catalog_service.alias_products_by_norm(session, chain, [TOMATOES])
    # Two products in the chain's memory: the alias with no barcode, as before.
    assert found == {catalog_service.normalize_he(TOMATOES): own.product_id}


def test_a_file_item_of_another_chain_does_not_remember(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID, other_chain: uuid.UUID
) -> None:
    _product(factory, "עגבניות שרי ארוז", "7290000000191")
    _final_alias(engine, factory, chain, TOMATOES, "7290000000191")
    with factory() as session:
        assert catalog_service.alias_products_by_norm(session, other_chain, [TOMATOES]) == {}


def test_a_valid_barcode_with_no_product_is_not_settled_by_memory(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _product(factory, "עגבניות שרי ארוז", "7290000000211")
    _final_alias(engine, factory, chain, TOMATOES, "7290000000211")
    result, record = _match_logged(factory, caplog, TOMATOES, chain, "7290000000212")
    assert result.state != "final"
    assert (record.path, record.memory_scope) == ("text", None)
    # The barcode gets a product later: it wins.
    later = _product(factory, "עגבניות שרי בקופסה", "7290000000212")
    again = _match(factory, TOMATOES, chain, "7290000000212")
    assert (again.state, again.product_id, again.alias_id) == ("certain", later, result.alias_id)


def _own_alias(
    engine: Engine,
    factory: sessionmaker[Session],
    chain_id: uuid.UUID,
    state: str,
    product_id: uuid.UUID,
) -> uuid.UUID:
    """The chain's alias of TOMATOES with no barcode, in this state for product_id."""
    first = _match(factory, TOMATOES, chain_id)
    assert first.alias_id is not None
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE product_aliases SET state = :s, product_id = :p WHERE id = :id"),
            {"s": state, "p": product_id, "id": first.alias_id},
        )
    return first.alias_id


def _two_products(factory: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    return (
        _product(factory, "עגבניות שרי אדומות", "7290000000221"),
        _product(factory, "עגבניות שרי צהובות", "7290000000222"),
    )


def _known(factory: sessionmaker[Session], chain_id: uuid.UUID) -> dict[str, uuid.UUID]:
    with factory() as session:
        return catalog_service.alias_products_by_norm(session, chain_id, [TOMATOES])


def test_memory_takes_the_place_of_an_uncertain_alias_in_a_file(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    red, yellow = _two_products(factory)
    _own_alias(engine, factory, chain, "uncertain", red)
    _final_alias(engine, factory, chain, TOMATOES, "7290000000222")
    assert _known(factory, chain) == {catalog_service.normalize_he(TOMATOES): yellow}


def test_a_disputed_alias_is_not_replaced_by_memory(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    red, _ = _two_products(factory)
    own = _own_alias(engine, factory, chain, "disputed", red)
    _final_alias(engine, factory, chain, TOMATOES, "7290000000222")
    assert _known(factory, chain) == {catalog_service.normalize_he(TOMATOES): red}
    result = _match(factory, TOMATOES, chain)
    assert (result.state, result.product_id, result.alias_id) == ("disputed", red, own)


def test_a_certain_alias_is_made_final_by_memory(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    red, yellow = _two_products(factory)
    own = _own_alias(engine, factory, chain, "certain", red)
    _final_alias(engine, factory, chain, TOMATOES, "7290000000222")
    result = _match(factory, TOMATOES, chain)
    assert (result.state, result.product_id, result.alias_id) == ("final", yellow, own)


def test_an_alias_with_votes_is_not_replaced_by_memory(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    red, _ = _two_products(factory)
    own = _own_alias(engine, factory, chain, "uncertain", red)
    voter = _operator(engine)
    with factory() as session:
        outcome = matching_service.record_vote(session, own, voter, "confirm", now=NOW)
        session.commit()
    assert outcome.state == "uncertain"
    _final_alias(engine, factory, chain, TOMATOES, "7290000000222")
    result = _match(factory, TOMATOES, chain)
    assert (result.state, result.product_id, result.alias_id) == ("uncertain", red, own)

    def no_match(*_a: Any, **_k: Any) -> MatchResult:
        raise AssertionError("match() was called")

    monkeypatch.setattr(matching_service, "match", no_match)
    with factory() as session:
        found = matching_service.match_file_items(session, chain, [FileItem(TOMATOES)], now=NOW)
    assert found == [red]


# --- the acceptance criteria ---


def test_ac_a_final_match_is_not_asked_again_in_its_chain(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    tomatoes = _product(factory, "עגבניות שרי ארוז", "7290000000201")
    first = _match(factory, TOMATOES, chain, "7290000000201")
    assert first.alias_id is not None
    operator = _operator(engine)
    with factory() as session:
        matching_service.approve_match(session, first.alias_id, operator, now=NOW)
        session.commit()
    result = _match(factory, TOMATOES, chain)
    assert (result.state, result.product_id, result.needs_confirmation) == (
        "final",
        tomatoes,
        False,
    )


def _operator(engine: Engine) -> uuid.UUID:
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, firebase_uid) VALUES (:id, :uid)"),
            {"id": user_id, "uid": f"uid-{user_id.hex}"},
        )
    return user_id
