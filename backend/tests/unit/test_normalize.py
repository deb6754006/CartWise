"""catalog.service.normalize_he: the one place text is normalized for search."""

import unicodedata

import pytest

from app.modules.catalog.service import normalize_he


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("מותג", "מותג", id="plain"),
        pytest.param("מוּתָּג", "מותג", id="niqqud"),
        pytest.param("\ufb2aל", "של", id="presentation-form-with-niqqud"),
        pytest.param("מֽ֑ותג", "מותג", id="cantillation"),
        pytest.param("מותג א'", "מותג א", id="ascii-apostrophe"),
        pytest.param("מותג א׳", "מותג א", id="hebrew-geresh"),
        pytest.param("מותג א\u2019", "מותג א", id="curly-apostrophe"),
        pytest.param("מות`ג", "מותג", id="backtick"),
        pytest.param('תנ"ך', "תנך", id="ascii-quote"),
        pytest.param("תנ״ך", "תנך", id="hebrew-gershayim"),
        pytest.param("\u201cמותג\u201d", "מותג", id="curly-quotes"),
        pytest.param("  מותג \t\n  א  ", "מותג א", id="whitespace"),
        pytest.param("מותג\u00a0א", "מותג א", id="non-breaking-space"),
        pytest.param("מותג ' א", "מותג א", id="whitespace-left-by-a-removed-quote"),
        pytest.param("BrAnD", "brand", id="latin-lowercase"),
        pytest.param("Cafe\u0301", "caf\u00e9", id="latin-composed"),
        pytest.param("מותג-א", "מותג א", id="hyphen-is-a-space"),
        pytest.param("מותג\u05bea", "מותג a", id="maqaf-is-a-space"),
        pytest.param("מותג\u2010א", "מותג א", id="unicode-hyphen-is-a-space"),
        pytest.param("מותג\u2011א", "מותג א", id="non-breaking-hyphen-is-a-space"),
        pytest.param("מותג\u2012א", "מותג א", id="figure-dash-is-a-space"),
        pytest.param("מותג\u2013א", "מותג א", id="en-dash-is-a-space"),
        pytest.param("מותג\u2014א", "מותג א", id="em-dash-is-a-space"),
        pytest.param("מותג\u2015א", "מותג א", id="horizontal-bar-is-a-space"),
        pytest.param("מותג - א", "מותג א", id="whitespace-left-by-a-hyphen"),
        pytest.param("מו\u200eתג", "מותג", id="left-to-right-mark"),
        pytest.param("מו\u200fתג", "מותג", id="right-to-left-mark"),
        pytest.param("מו\u202aתג", "מותג", id="left-to-right-embedding"),
        pytest.param("מו\u202bתג", "מותג", id="right-to-left-embedding"),
        pytest.param("מו\u202cתג", "מותג", id="pop-directional-formatting"),
        pytest.param("מו\u202dתג", "מותג", id="left-to-right-override"),
        pytest.param("מו\u202eתג", "מותג", id="right-to-left-override"),
        pytest.param("מו\u200bתג", "מותג", id="zero-width-space"),
        pytest.param("\ufeffמותג", "מותג", id="byte-order-mark"),
        pytest.param("\u200fמ\u200f", "מ", id="format-characters-do-not-count-as-length"),
        pytest.param("%_\\", "%_\\", id="special-characters-kept"),
        pytest.param("", "", id="empty"),
        pytest.param(" ׳״ ", "", id="nothing-left"),
    ],
)
def test_normalize_he(raw: str, expected: str) -> None:
    assert normalize_he(raw) == expected


@pytest.mark.parametrize(
    "quote",
    [
        "\u0027",
        "\u0060",
        "\u00b4",
        "\u05f3",
        "\u2018",
        "\u2019",
        "\u201a",
        "\u201b",
        "\u0022",
        "\u05f4",
        "\u201c",
        "\u201d",
        "\u201e",
        "\u201f",
    ],
)
def test_normalize_he_removes_every_quote(quote: str) -> None:
    assert normalize_he(f"מו{quote}תג") == "מותג"


@pytest.mark.parametrize("raw", ["מוּתָּג א׳", "\ufb2aל", "Cafe\u0301  'X'", "  ׳ "])
def test_result_is_nfc_and_stable(raw: str) -> None:
    once = normalize_he(raw)
    assert unicodedata.is_normalized("NFC", once)
    assert normalize_he(once) == once
