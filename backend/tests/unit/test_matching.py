"""Barcode matching (Story 4.1), with no database. Every barcode here is invented."""

import uuid
from typing import Any

import pytest

from app.modules.catalog.service import MAX_ALIAS_NORM_LENGTH, clean_alias_text, valid_barcode
from app.modules.matching import service as matching_service
from app.modules.matching.service import UNMATCHED, MatchContext, MatchResult, match


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        pytest.param("12345678", "12345678", id="eight-digits"),
        pytest.param("12345678901234", "12345678901234", id="fourteen-digits"),
        pytest.param("7290000000001", "7290000000001", id="ean-13"),
        pytest.param("0072900000001", "0072900000001", id="leading-zeros-kept"),
        pytest.param("  7290000000001\t", "7290000000001", id="whitespace-at-the-ends"),
        # A wrong check digit is still a barcode: real files have them.
        pytest.param("7290000000002", "7290000000002", id="no-check-digit-test"),
        pytest.param("1234567", None, id="seven-digits"),
        pytest.param("123456789012345", None, id="fifteen-digits"),
        pytest.param("123", None, id="short"),
        pytest.param("00000000", None, id="all-zeros"),
        pytest.param("00000000000000", None, id="all-zeros-long"),
        pytest.param("abc", None, id="letters"),
        pytest.param("1234 5678", None, id="inner-space"),
        pytest.param("12345678a", None, id="trailing-letter"),
        pytest.param("١٢٣٤٥٦٧٨", None, id="non-ascii-digits"),
        pytest.param("", None, id="empty"),
        pytest.param("   ", None, id="blank"),
    ],
)
def test_valid_barcode(code: str, expected: str | None) -> None:
    assert valid_barcode(code) == expected


def test_clean_alias_text() -> None:
    assert clean_alias_text("  חלב   3%\t1ל ") == "חלב 3% 1ל"
    assert clean_alias_text("   ") is None
    assert clean_alias_text("\"'") is None  # nothing left after normalizing
    assert clean_alias_text("חלב\x00בדוי") == "חלב בדוי"


def test_a_too_long_alias_text_is_rejected() -> None:
    assert clean_alias_text("א" * MAX_ALIAS_NORM_LENGTH) == "א" * MAX_ALIAS_NORM_LENGTH
    assert clean_alias_text("א" * (MAX_ALIAS_NORM_LENGTH + 1)) is None
    # Measured normalized: quotes dropped do not count.
    assert clean_alias_text("א" * MAX_ALIAS_NORM_LENGTH + '"' * 10) == "א" * 500 + '"' * 10


def test_a_too_long_alias_is_unmatched_without_the_database() -> None:
    session: Any = _NoSession()
    long_text = "א" * (MAX_ALIAS_NORM_LENGTH + 1)
    assert match(session, long_text, uuid.uuid4(), "7290000000001") == UNMATCHED


class _NoSession:
    """Any use of it fails the test: unmatched must not touch the database."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"session.{name} used")


@pytest.mark.parametrize(
    ("text", "barcode"),
    [
        pytest.param("   ", "7290000000001", id="blank-with-barcode"),
        pytest.param("   ", None, id="blank-no-barcode"),
        pytest.param("\"'", None, id="quotes-only"),
        pytest.param("", "123", id="empty-bad-barcode"),
    ],
)
def test_unmatched_does_not_touch_the_database(text: str, barcode: str | None) -> None:
    # Since Story 4.2 any other text is matched by text: only an empty one is unmatched.
    session: Any = _NoSession()
    result = match(session, text, uuid.uuid4(), barcode, MatchContext("receipt", 990))
    assert result == UNMATCHED
    assert result == MatchResult("unmatched", None, None, None, ())


def test_match_barcodes_with_no_valid_barcode_does_not_touch_the_database() -> None:
    session: Any = _NoSession()
    items = [("א", None), ("ב", "123"), ("ג", "00000000")]
    assert matching_service.match_barcodes(session, uuid.uuid4(), items) == 0


def test_the_match_log_has_no_alias_text(caplog: pytest.LogCaptureFixture) -> None:
    session: Any = _NoSession()
    with caplog.at_level("INFO", logger="app.matching"):
        # Too long to be an alias: unmatched, with no database.
        match(session, "חלב סודי " * 100, uuid.uuid4(), "123", MatchContext("official_file"))
    [record] = [r for r in caplog.records if r.getMessage() == "matching_match"]
    assert (record.state, record.source, record.had_barcode) == (  # type: ignore[attr-defined]
        "unmatched",
        "official_file",
        True,
    )
    assert "חלב סודי" not in str(record.__dict__)
