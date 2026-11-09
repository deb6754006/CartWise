"""Matching by text (Story 4.2), with no database: pack sizes, scoring and the decision. Every
product here is invented."""

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.catalog.models import PackUnit, ProductStatus
from app.modules.catalog.service import ProductCandidate, normalize_he
from app.modules.matching.service import (
    WEIGHT_PRICE,
    WEIGHT_SIZE,
    WEIGHT_TEXT,
    WEIGHT_UNIT,
    Candidate,
    Thresholds,
    decide,
    parse_pack,
    proposed_ids,
    score_candidates,
    score_gap,
    text_similarity,
    trigram_similarity,
)

LIMITS = Thresholds(certain=0.85, min_gap=0.10, new_product_below=0.30)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.5ל", (Decimal("1.5"), "l")),
        ("750 מל", (Decimal(750), "ml")),
        ('750 מ"ל', (Decimal(750), "ml")),
        ("750מל", (Decimal(750), "ml")),
        ("80ג", (Decimal(80), "g")),
        ("80 גרם", (Decimal(80), "g")),
        ("80 גר", (Decimal(80), "g")),
        ("1 קג", (Decimal(1), "kg")),
        ('1 ק"ג', (Decimal(1), "kg")),
        ("1קג", (Decimal(1), "kg")),
        ("6 יח", (Decimal(6), "unit")),
        ("6 יח'", (Decimal(6), "unit")),
        ("1ל", (Decimal(1), "l")),
        ("1 ליטר", (Decimal(1), "l")),
        ("1,5 ליטר", (Decimal("1.5"), "l")),
        ("1,000 גרם", (Decimal(1000), "g")),
        ("1,25 ליטר", (Decimal("1.25"), "l")),
        ("חלב 3% 1ל", (Decimal(1), "l")),
        ("עגבניות שרי 250ג", (Decimal(250), "g")),
        ("שוקולד", (None, None)),
        ("2 גבינות", (None, None)),  # a word that starts like a unit is not one
        ("0 גרם", (None, None)),
        ("", (None, None)),
    ],
)
def test_parse_pack(text: str, expected: tuple[Decimal | None, PackUnit | None]) -> None:
    assert parse_pack(normalize_he(text)) == expected


def test_parse_pack_takes_the_last() -> None:
    assert parse_pack(normalize_he("מארז 6 יח 330 מל")) == (Decimal(330), "ml")


def test_trigram_similarity_as_pg_trgm() -> None:
    assert trigram_similarity("חלב", "חלב") == 1.0
    assert trigram_similarity("חלב", "") == 0.0
    # 'word' is 5 trigrams ("  w", " wo", "wor", "ord", "rd "), 'words' 6; they share 4.
    assert trigram_similarity("word", "words") == pytest.approx(4 / 7)


def test_text_similarity_leaves_the_pack_out() -> None:
    assert text_similarity("עגבניות שרי 250ג", "עגבניות שרי 250 גרם") == 1.0
    assert trigram_similarity("עגבניות שרי 250ג", "עגבניות שרי 250 גרם") < 1.0


def _product(
    name: str,
    size: Decimal | None = None,
    unit: PackUnit | None = None,
    product_id: uuid.UUID | None = None,
    status: ProductStatus = "active",
) -> ProductCandidate:
    return ProductCandidate(product_id or uuid.uuid4(), normalize_he(name), size, unit, status, 0.5)


def test_text_alone_is_the_similarity() -> None:
    product = _product("קפה שחור טחון")
    [scored] = score_candidates(normalize_he("קפה שחור"), [product])
    assert scored.score == pytest.approx(text_similarity("קפה שחור", "קפה שחור טחון"))


def test_size_and_unit_from_the_product_columns() -> None:
    product = _product("חלב", Decimal(1), "l")
    [scored] = score_candidates(normalize_he("חלב 1000 מל"), [product])
    assert scored.score == pytest.approx(1.0)


def test_size_and_unit_from_the_product_name() -> None:
    one, two = _product("חלב 1 ליטר"), _product("חלב 2 ליטר")
    scored = score_candidates(normalize_he("חלב 1ל"), [two, one])
    assert [c.product_id for c in scored] == [one.id, two.id]
    assert scored[0].score == pytest.approx(1.0)
    expected = (WEIGHT_TEXT + WEIGHT_UNIT) / (WEIGHT_TEXT + WEIGHT_SIZE + WEIGHT_UNIT)
    assert scored[1].score == pytest.approx(expected)


def test_a_size_within_two_percent() -> None:
    product = _product("קמח", Decimal(1000), "g")
    [near] = score_candidates(normalize_he("קמח 1.02 קג"), [product])
    [far] = score_candidates(normalize_he("קמח 1.03 קג"), [product])
    assert near.score == pytest.approx(1.0)
    assert far.score < near.score


def test_another_dimension() -> None:
    product = _product("שמן", Decimal(1), "l")
    [scored] = score_candidates(normalize_he("שמן 1 קג"), [product])
    total = WEIGHT_TEXT + WEIGHT_SIZE + WEIGHT_UNIT
    assert scored.score == pytest.approx(WEIGHT_TEXT / total)


def test_a_size_on_the_alias_only_scores_zero() -> None:
    product = _product("עגבניות שרי")
    [scored] = score_candidates(normalize_he("עגבניות שרי 250ג"), [product])
    total = WEIGHT_TEXT + WEIGHT_SIZE + WEIGHT_UNIT
    assert scored.score == pytest.approx(WEIGHT_TEXT / total)


def test_a_size_on_the_product_only_is_left_out() -> None:
    product = _product("עגבניות שרי 250 גרם")
    [scored] = score_candidates(normalize_he("עגבניות שרי"), [product])
    assert scored.score == pytest.approx(1.0)


def test_a_generic_product_does_not_beat_another_size() -> None:
    generic, two = _product("חלב"), _product("חלב 2 ליטר")
    scored = score_candidates(normalize_he("חלב 1ל"), [generic, two])
    assert [c.product_id for c in scored] == [two.id, generic.id]


def test_the_price() -> None:
    product = _product("חלב 1 ליטר")
    alias = normalize_he("חלב 1ל")
    total = WEIGHT_TEXT + WEIGHT_SIZE + WEIGHT_UNIT + WEIGHT_PRICE
    [sane] = score_candidates(alias, [product], 1000, {product.id: 700})
    [insane] = score_candidates(alias, [product], 3000, {product.id: 1000})
    assert sane.score == pytest.approx(1.0)
    assert insane.score == pytest.approx((total - WEIGHT_PRICE) / total)
    assert insane.score < sane.score
    # No median, or no price: the price is left out.
    [unknown] = score_candidates(alias, [product], 3000, {})
    [no_price] = score_candidates(alias, [product], None, {product.id: 1000})
    assert unknown.score == no_price.score == pytest.approx(1.0)


def test_ties_by_id() -> None:
    low, high = uuid.UUID(int=1), uuid.UUID(int=2)
    scored = score_candidates(
        "חלב", [_product("חלב", product_id=high), _product("חלב", None, None, low)]
    )
    assert [c.product_id for c in scored] == [low, high]


def _scored(*scores: float) -> list[Candidate]:
    return [Candidate(uuid.uuid4(), s) for s in scores]


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ((0.9,), "certain"),
        ((0.85,), "certain"),
        ((0.95, 0.84), "certain"),
        ((0.95, 0.86), "uncertain"),  # too close to the second
        ((0.849,), "uncertain"),
        ((0.6, 0.2), "uncertain"),
        ((0.3,), "uncertain"),
        ((0.299, 0.2), "new_product_proposal"),
        ((), "new_product_proposal"),
    ],
)
def test_decide(scores: tuple[float, ...], expected: str) -> None:
    assert decide(_scored(*scores), LIMITS) == expected


def test_a_proposed_product_is_not_certain() -> None:
    scored = _scored(1.0)
    assert decide(scored, LIMITS, {scored[0].product_id}) == "uncertain"
    assert decide(scored, LIMITS, {uuid.uuid4()}) == "certain"
    product = _product("חלב", status="proposed")
    assert proposed_ids([product, _product("לחם")]) == {product.id}


def test_decide_does_not_round() -> None:
    assert decide(_scored(0.8496), LIMITS) == "uncertain"


def test_score_gap() -> None:
    assert score_gap([]) == 0.0
    assert score_gap(_scored(0.7)) == 0.7
    assert score_gap(_scored(0.7, 0.5)) == pytest.approx(0.2)


def test_the_thresholds_settings() -> None:
    settings = Settings()
    assert (
        settings.MATCH_CERTAIN_THRESHOLD,
        settings.MATCH_MIN_GAP,
        settings.MATCH_NEW_PRODUCT_BELOW,
    ) == (0.85, 0.10, 0.30)
    with pytest.raises(ValidationError, match="MATCH_NEW_PRODUCT_BELOW"):
        Settings(MATCH_CERTAIN_THRESHOLD=0.5, MATCH_NEW_PRODUCT_BELOW=0.5)
    with pytest.raises(ValidationError):
        Settings(MATCH_MIN_GAP=1.5)


def test_eval_matching_refuses_prod(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import eval_matching

    prod = Settings(
        ENV="prod",
        DATABASE_URL="postgresql+psycopg://nobody@127.0.0.1:1/none",
        DEVICE_TOKEN_SECRET="x" * 40,
    )
    monkeypatch.setattr(eval_matching, "get_settings", lambda: prod)
    assert eval_matching.main([]) == 1
    assert "ENV=prod" in capsys.readouterr().err
    # Allowed: it goes on, and stops at the database here.
    assert eval_matching.main(["--allow-prod"]) == 1
    assert "no database" in capsys.readouterr().err
