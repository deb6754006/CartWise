"""Votes and final matches (Story 4.3), against Postgres. Every product here is invented."""

import threading
import uuid
from collections.abc import Collection, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.db import make_engine
from app.core.errors import AppError
from app.modules.catalog import service as catalog_service
from app.modules.catalog.service import ProductRecord
from app.modules.identity import service as identity_service
from app.modules.matching import service as matching_service
from app.modules.matching.models import VoteKind
from app.modules.matching.service import TrustGate, VoteOutcome
from tests.integration.pg import alembic_config, create_database

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
_codes = iter(range(10**12, 10**13))


@pytest.fixture(scope="module")
def votes_url(db_url: str) -> str:
    """A database of its own: these tests truncate and count rows."""
    url = create_database(db_url, "cw_match_votes")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="module")
def engine(votes_url: str) -> Iterator[Engine]:
    eng = make_engine(votes_url)
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


@pytest.fixture
def chain(factory: sessionmaker[Session]) -> uuid.UUID:
    with factory() as session:
        chain_id = catalog_service.ensure_chain(session, "7290000000000", "רשת בדויה")
        session.commit()
    return chain_id


def _product(factory: sessionmaker[Session], name: str = "מוצר בדוי") -> uuid.UUID:
    code = str(next(_codes))
    with factory() as session:
        ids = catalog_service.ensure_products_by_barcode(
            session, [ProductRecord(code, name, None, None, False)], now=NOW
        )
        session.commit()
    return ids[code]


def _alias(
    engine: Engine,
    chain_id: uuid.UUID,
    product_id: uuid.UUID | None,
    state: str = "uncertain",
    text_: str | None = None,
    confidence: Decimal | None = Decimal("0.6"),
) -> uuid.UUID:
    alias_id = uuid.uuid4()
    name = text_ or f"כינוי {alias_id.hex[:8]}"
    norm = catalog_service.alias_norm(name)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO product_aliases (id, chain_id, alias_text, alias_norm, product_id, "
                "state, confidence, created_at, updated_at) "
                "VALUES (:id, :chain, :t, :n, :p, :s, :c, :now, :now)"
            ),
            {
                "id": alias_id,
                "chain": chain_id,
                "t": name,
                "n": norm,
                "p": product_id,
                "s": state,
                "c": confidence,
                "now": NOW,
            },
        )
    return alias_id


def _user(engine: Engine, deleted: bool = False) -> uuid.UUID:
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, firebase_uid, deleted_at) VALUES (:id, :uid, :d)"),
            {"id": user_id, "uid": f"uid-{user_id.hex}", "d": NOW if deleted else None},
        )
    return user_id


def _vote(
    factory: sessionmaker[Session],
    alias_id: uuid.UUID,
    user_id: uuid.UUID,
    vote: VoteKind = "confirm",
    product_id: uuid.UUID | None = None,
    trust: TrustGate | None = None,
    now: datetime = NOW,
) -> VoteOutcome:
    with factory() as session:
        outcome = matching_service.record_vote(
            session, alias_id, user_id, vote, product_id, now=now, trust=trust
        )
        session.commit()
    return outcome


def _approve(
    factory: sessionmaker[Session],
    alias_id: uuid.UUID,
    operator: uuid.UUID,
    product_id: uuid.UUID | None = None,
) -> VoteOutcome:
    with factory() as session:
        outcome = matching_service.approve_match(session, alias_id, operator, product_id, now=NOW)
        session.commit()
    return outcome


def _rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql), params)]


def _alias_row(engine: Engine, alias_id: uuid.UUID) -> dict[str, Any]:
    [row] = _rows(engine, "SELECT * FROM product_aliases WHERE id = :id", id=alias_id)
    return row


def _votes(engine: Engine) -> list[dict[str, Any]]:
    return _rows(engine, "SELECT * FROM match_votes ORDER BY created_at, id")


# --- the matrix ---


def test_three_confirms_make_it_final(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    product = _product(factory)
    alias = _alias(engine, chain, product)
    users = [_user(engine) for _ in range(3)]
    first = _vote(factory, alias, users[0])
    second = _vote(factory, alias, users[1])
    assert (first.state, first.changed, second.state, second.changed) == (
        "uncertain",
        False,
        "uncertain",
        False,
    )
    third = _vote(factory, alias, users[2], now=LATER)
    assert third == VoteOutcome(alias, "final", product, True)
    row = _alias_row(engine, alias)
    assert (row["state"], row["product_id"], row["confidence"]) == ("final", product, Decimal(1))
    assert row["updated_at"] == LATER


def test_two_confirms_are_not_enough(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    alias = _alias(engine, chain, _product(factory))
    for _ in range(2):
        _vote(factory, alias, _user(engine))
    assert _alias_row(engine, alias)["state"] == "uncertain"


def test_the_same_user_counts_once(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    alias = _alias(engine, chain, _product(factory))
    user = _user(engine)
    for _ in range(3):
        outcome = _vote(factory, alias, user)
    assert outcome.state == "uncertain"
    assert len(_votes(engine)) == 1


def test_a_majority_for_another_product_moves_the_alias(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a, b = _product(factory, "מוצר א"), _product(factory, "מוצר ב")
    alias = _alias(engine, chain, a)
    _vote(factory, alias, _user(engine), "confirm")
    tie = _vote(factory, alias, _user(engine), "other", b)
    assert (tie.state, tie.product_id, tie.changed) == ("uncertain", a, False)
    moved = _vote(factory, alias, _user(engine), "other", b)
    assert moved == VoteOutcome(alias, "disputed", b, True)
    row = _alias_row(engine, alias)
    assert (row["state"], row["product_id"], row["confidence"]) == ("disputed", b, None)
    # The confirm vote stays with A, the product it confirmed.
    kinds = sorted((v["vote"], v["product_id"]) for v in _votes(engine))
    assert kinds == sorted([("other", a), ("other", b), ("other", b)])


def test_disputed_then_final(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a, b = _product(factory, "מוצר א"), _product(factory, "מוצר ב")
    alias = _alias(engine, chain, a)
    _vote(factory, alias, _user(engine), "confirm")
    _vote(factory, alias, _user(engine), "other", b)
    assert _vote(factory, alias, _user(engine), "other", b).state == "disputed"
    final = _vote(factory, alias, _user(engine), "other", b)
    assert final == VoteOutcome(alias, "final", b, True)
    # other for the alias's current product is kept as confirm.
    assert sorted(v["vote"] for v in _votes(engine)) == ["confirm", "other", "other", "other"]


def test_a_tie_changes_nothing(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a, b = _product(factory, "מוצר א"), _product(factory, "מוצר ב")
    alias = _alias(engine, chain, a)
    _vote(factory, alias, _user(engine), "confirm")
    outcome = _vote(factory, alias, _user(engine), "other", b, now=LATER)
    assert (outcome.state, outcome.product_id, outcome.changed) == ("uncertain", a, False)
    assert _alias_row(engine, alias)["updated_at"] == NOW


def test_unknown_is_no_vote(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    alias = _alias(engine, chain, _product(factory))
    for _ in range(3):
        outcome = _vote(factory, alias, _user(engine), "unknown")
    assert (outcome.state, outcome.changed) == ("uncertain", False)
    assert [v["product_id"] for v in _votes(engine)] == [None, None, None]


class _Distrust:
    def __init__(self, distrusted: uuid.UUID) -> None:
        self.distrusted = distrusted

    def counting(self, session: Session, user_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
        return set(user_ids) - {self.distrusted}


def test_an_untrusted_user_does_not_count(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    alias = _alias(engine, chain, _product(factory))
    users = [_user(engine) for _ in range(3)]
    gate = _Distrust(users[1])
    for user in users:
        outcome = _vote(factory, alias, user, trust=gate)
    assert outcome.state == "uncertain"


def test_a_deleted_user_does_not_count(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    alias = _alias(engine, chain, _product(factory))
    gone = _user(engine)
    _vote(factory, alias, gone)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET deleted_at = :d WHERE id = :id"), {"d": NOW, "id": gone}
        )
    _vote(factory, alias, _user(engine))
    assert _vote(factory, alias, _user(engine)).state == "uncertain"
    assert _vote(factory, alias, _user(engine)).state == "final"


def test_operator_approval(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    product = _product(factory)
    alias = _alias(engine, chain, product)
    operator = _user(engine)
    assert _approve(factory, alias, operator) == VoteOutcome(alias, "final", product, True)
    row = _alias_row(engine, alias)
    assert (row["state"], row["confidence"]) == ("final", Decimal(1))
    [vote] = _votes(engine)
    assert (vote["role"], vote["vote"], vote["user_id"]) == ("operator", "confirm", operator)
    # Approved again: nothing changes.
    assert _approve(factory, alias, operator).changed is False


def test_operator_chooses_another_product(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a, b = _product(factory, "מוצר א"), _product(factory, "מוצר ב")
    alias = _alias(engine, chain, a)
    user = _user(engine)
    _vote(factory, alias, user, "confirm")
    assert _approve(factory, alias, _user(engine), b) == VoteOutcome(alias, "final", b, True)
    assert _alias_row(engine, alias)["product_id"] == b
    votes = {v["role"]: (v["vote"], v["product_id"]) for v in _votes(engine)}
    assert votes == {"user": ("other", a), "operator": ("other", b)}


@pytest.mark.parametrize("state", ["disputed", "final"])
def test_operator_overrides_a_settled_alias(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID, state: str
) -> None:
    a, b = _product(factory, "מוצר א"), _product(factory, "מוצר ב")
    alias = _alias(engine, chain, a, state=state, confidence=None)
    assert _approve(factory, alias, _user(engine), b) == VoteOutcome(alias, "final", b, True)


def test_votes_do_not_change_a_final_alias(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a, b = _product(factory, "מוצר א"), _product(factory, "מוצר ב")
    alias = _alias(engine, chain, a, state="final", confidence=Decimal(1))
    for _ in range(3):
        outcome = _vote(factory, alias, _user(engine), "other", b)
    assert outcome == VoteOutcome(alias, "final", a, False)
    assert _alias_row(engine, alias)["product_id"] == a
    assert len(_votes(engine)) == 3


def test_other_with_no_product(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    alias = _alias(engine, chain, _product(factory))
    with pytest.raises(AppError) as err:
        _vote(factory, alias, _user(engine), "other", None)
    assert (err.value.code, err.value.status) == ("invalid_vote", 422)
    assert _votes(engine) == []


def test_other_with_a_missing_or_merged_product(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    alias = _alias(engine, chain, _product(factory))
    merged = _product(factory, "מוצר ממוזג")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE products SET status = 'merged_into' WHERE id = :id"), {"id": merged}
        )
    for product in (uuid.uuid4(), merged):
        with pytest.raises(AppError) as err:
            _vote(factory, alias, _user(engine), "other", product)
        assert (err.value.code, err.value.status) == ("invalid_vote", 422)


def test_a_missing_alias(engine: Engine, factory: sessionmaker[Session]) -> None:
    user = _user(engine)
    for call in (
        lambda: _vote(factory, uuid.uuid4(), user),
        lambda: _approve(factory, uuid.uuid4(), user),
    ):
        with pytest.raises(AppError) as err:
            call()
        assert (err.value.code, err.value.status) == ("alias_not_found", 404)


def test_account_deletion_removes_the_votes(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    product = _product(factory)
    alias = _alias(engine, chain, product)
    users = [_user(engine) for _ in range(3)]
    for user in users:
        _vote(factory, alias, user)
    other_alias = _alias(engine, chain, product)
    _vote(factory, other_alias, users[0])
    with factory() as session:
        identity_service.delete_account(session, users[0])
    assert {v["user_id"] for v in _votes(engine)} == {users[1], users[2]}
    # The alias is not evaluated again: final stays final.
    assert _alias_row(engine, alias)["state"] == "final"
    assert _alias_row(engine, other_alias)["state"] == "uncertain"


def test_the_weakest_state_for_reliability(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    x, y, z = _product(factory, "מוצר א"), _product(factory, "מוצר ב"), _product(factory, "ג")
    _alias(engine, chain, x, state="final", confidence=Decimal(1))
    _alias(engine, chain, x, state="uncertain")
    _alias(engine, chain, y, state="certain")
    _alias(engine, chain, y, state="disputed", confidence=None)
    with factory() as session:
        found = (
            matching_service.alias_state_for_product(session, chain, x),
            matching_service.alias_state_for_product(session, chain, y),
            matching_service.alias_state_for_product(session, chain, z),
        )
    assert found == ("uncertain", "disputed", None)


def test_the_weakest_state_is_per_chain(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    x = _product(factory)
    with factory() as session:
        other_chain = catalog_service.ensure_chain(session, "7290000000001", "רשת אחרת")
        session.commit()
    _alias(engine, chain, x, state="final", confidence=Decimal(1))
    _alias(engine, other_chain, x, state="uncertain")
    with factory() as session:
        assert matching_service.alias_state_for_product(session, chain, x) == "final"


def test_the_final_threshold_is_a_setting(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MATCH_FINAL_VOTES", "1")
    get_settings.cache_clear()
    try:
        alias = _alias(engine, chain, _product(factory))
        assert _vote(factory, alias, _user(engine)).state == "final"
    finally:
        monkeypatch.delenv("MATCH_FINAL_VOTES")
        get_settings.cache_clear()


def test_the_evaluation_log(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    alias = _alias(engine, chain, _product(factory))
    users = [_user(engine) for _ in range(3)]
    with caplog.at_level("INFO", logger="app.matching"):
        for user in users:
            _vote(factory, alias, user)
    [record] = [r for r in caplog.records if r.getMessage() == "matching_vote_evaluated"]
    assert (record.alias_id, record.state, record.votes) == (  # type: ignore[attr-defined]
        str(alias),
        "final",
        3,
    )
    logged = " ".join(str(v) for v in record.__dict__.values())
    assert not any(str(user) in logged for user in users)


def test_the_table_requires_a_product_for_other(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    alias = _alias(engine, chain, _product(factory))
    user = _user(engine)
    with pytest.raises(Exception, match="ck_match_votes_product_id"), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO match_votes (id, alias_id, user_id, product_id, vote, role, "
                "created_at, updated_at) VALUES (:id, :a, :u, NULL, 'other', 'user', now(), now())"
            ),
            {"id": uuid.uuid4(), "a": alias, "u": user},
        )


# --- after review ---


def test_match_does_not_move_an_alias_with_votes(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a, b = _product(factory, "מוצר אחר לגמרי"), _product(factory, "שוקולד חלב אגוזים")
    alias = _alias(engine, chain, a, text_="שוקולד חלב אגוזים")
    _vote(factory, alias, _user(engine))
    with factory() as session:
        result = matching_service.match(session, "שוקולד חלב אגוזים", chain, now=LATER)
        session.commit()
    assert (result.alias_id, result.product_id, result.state) == (alias, a, "uncertain")
    row = _alias_row(engine, alias)
    assert (row["product_id"], row["updated_at"]) == (a, NOW)
    # With no votes, the same text (another key: with a barcode) goes to B.
    with factory() as session:
        fresh = matching_service.match(session, "שוקולד חלב אגוזים", chain, "7290000000999")
        session.rollback()
    assert fresh.product_id == b


def test_one_other_vote_alone_changes_nothing(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a, b = _product(factory, "מוצר א"), _product(factory, "מוצר ב")
    alias = _alias(engine, chain, a)
    outcome = _vote(factory, alias, _user(engine), "other", b)
    assert (outcome.state, outcome.product_id, outcome.changed) == ("uncertain", a, False)


def test_final_needs_a_majority(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a, b, c = _product(factory, "מוצר א"), _product(factory, "מוצר ב"), _product(factory, "ג")
    alias = _alias(engine, chain, a)
    votes: list[tuple[VoteKind, uuid.UUID | None]] = [
        ("confirm", None),
        ("confirm", None),
        ("other", b),
        ("other", b),
        ("other", c),
        ("other", c),
        ("confirm", None),
    ]
    for vote, product in votes:
        outcome = _vote(factory, alias, _user(engine), vote, product)
    # A=3, B=2, C=2: three votes, but not more than half.
    assert (outcome.state, outcome.product_id) == ("uncertain", a)


def test_a_plurality_without_a_majority_does_not_move(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a, b, c = _product(factory, "מוצר א"), _product(factory, "מוצר ב"), _product(factory, "ג")
    alias = _alias(engine, chain, a)
    _vote(factory, alias, _user(engine), "confirm")
    _vote(factory, alias, _user(engine), "other", c)
    _vote(factory, alias, _user(engine), "other", b)
    outcome = _vote(factory, alias, _user(engine), "other", b)
    # B=2 of 4: the most, and at least MIN_MOVE_VOTES, but not more than half.
    assert (outcome.state, outcome.product_id, outcome.changed) == ("uncertain", a, False)


def test_votes_for_a_merged_product_do_not_count(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a, b = _product(factory, "מוצר א"), _product(factory, "מוצר ב")
    alias = _alias(engine, chain, a)
    _vote(factory, alias, _user(engine), "confirm")
    _vote(factory, alias, _user(engine), "other", b)
    assert _vote(factory, alias, _user(engine), "other", b).product_id == b
    with engine.begin() as conn:
        conn.execute(text("UPDATE products SET status = 'merged_into' WHERE id = :id"), {"id": b})
    # A=2 and B=2, but B was merged: its votes go, and A has them all.
    outcome = _vote(factory, alias, _user(engine), "other", a)
    assert (outcome.state, outcome.product_id, outcome.changed) == ("disputed", a, True)


def test_confirm_on_an_alias_with_no_product(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    alias = _alias(engine, chain, None, confidence=None)
    with pytest.raises(AppError) as err:
        _vote(factory, alias, _user(engine), "confirm")
    assert (err.value.code, err.value.status) == ("invalid_vote", 422)
    assert _votes(engine) == []


def test_a_vote_that_is_not_one(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    alias = _alias(engine, chain, _product(factory))
    with pytest.raises(AppError) as err:
        _vote(factory, alias, _user(engine), "maybe")  # type: ignore[arg-type]
    assert (err.value.code, err.value.status) == ("invalid_vote", 422)


def test_a_missing_or_deleted_user(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    alias = _alias(engine, chain, _product(factory))
    for user in (uuid.uuid4(), _user(engine, deleted=True)):
        with pytest.raises(AppError) as err:
            _vote(factory, alias, user)
        assert (err.value.code, err.value.status) == ("user_not_found", 404)
    assert _votes(engine) == []


def test_a_user_vote_does_not_replace_an_operator_approval(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    a, b = _product(factory, "מוצר א"), _product(factory, "מוצר ב")
    alias = _alias(engine, chain, a)
    operator = _user(engine)
    _approve(factory, alias, operator)
    outcome = _vote(factory, alias, operator, "other", b, now=LATER)
    assert outcome == VoteOutcome(alias, "final", a, False)
    [vote] = _votes(engine)
    assert (vote["role"], vote["vote"], vote["product_id"]) == ("operator", "confirm", None)


def test_two_votes_at_once(
    engine: Engine, factory: sessionmaker[Session], chain: uuid.UUID
) -> None:
    product = _product(factory)
    alias = _alias(engine, chain, product)
    _vote(factory, alias, _user(engine))
    users = [_user(engine), _user(engine)]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def run(user: uuid.UUID) -> None:
        try:
            barrier.wait()
            _vote(factory, alias, user)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(user,)) for user in users]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []
    row = _alias_row(engine, alias)
    assert (row["state"], row["product_id"]) == ("final", product)


def test_a_second_move_keeps_the_confirms_with_their_product(
    engine: Engine,
    factory: sessionmaker[Session],
    chain: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MATCH_FINAL_VOTES", "10")
    get_settings.cache_clear()
    try:
        a, b, c = _product(factory, "מוצר א"), _product(factory, "מוצר ב"), _product(factory, "ג")
        alias = _alias(engine, chain, a)
        _vote(factory, alias, _user(engine), "other", b)
        assert _vote(factory, alias, _user(engine), "other", b).product_id == b
        confirmer = _user(engine)
        _vote(factory, alias, confirmer, "confirm")
        for _ in range(3):
            outcome = _vote(factory, alias, _user(engine), "other", c)
        assert (outcome.state, outcome.product_id) == ("disputed", b)  # C=3, B=3
        outcome = _vote(factory, alias, _user(engine), "other", c)
        assert (outcome.state, outcome.product_id) == ("disputed", c)  # C=4 of 7
        [mine] = [v for v in _votes(engine) if v["user_id"] == confirmer]
        assert (mine["vote"], mine["product_id"]) == ("other", b)
    finally:
        monkeypatch.delenv("MATCH_FINAL_VOTES")
        get_settings.cache_clear()


# --- the migration ---


def test_votes_migration_roundtrip(db_url: str) -> None:
    url = create_database(db_url, "cw_votes_roundtrip")
    cfg = alembic_config(url)
    eng = make_engine(url)
    try:
        command.upgrade(cfg, "0012")
        assert "match_votes" not in inspect(eng).get_table_names()
        command.upgrade(cfg, "0013")
        assert "match_votes" in inspect(eng).get_table_names()
        command.downgrade(cfg, "0012")
        assert "match_votes" not in inspect(eng).get_table_names()
    finally:
        eng.dispose()


def test_models_match_the_migrations(votes_url: str) -> None:
    command.check(alembic_config(votes_url))
