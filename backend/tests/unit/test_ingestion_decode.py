"""decode_xml and count_records (Story 3.2): gz, UTF-8 and UTF-16, size caps. No network, no DB."""

import gzip
from pathlib import Path
from xml.etree.ElementTree import ParseError

import pytest

from app.modules.ingestion.decode import XmlTooLargeError, count_records, decode_xml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingestion"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_utf16_stores_file_without_gz() -> None:
    data = _fixture("stores.utf16.xml")
    assert data[:2] == b"\xff\xfe"
    root = decode_xml(data)
    assert count_records("stores", root) == 2
    assert root.find(".//StoreName") is not None
    assert root.findtext(".//StoreName") == "סניף הדקל"


def test_utf16_big_endian() -> None:
    text = '<?xml version="1.0" encoding="UTF-16"?><Root><Store/><Store/><Store/></Root>'
    root = decode_xml(b"\xfe\xff" + text.encode("utf-16-be"))
    assert count_records("stores", root) == 3


def test_gz_utf8_price_and_promo_files() -> None:
    price = decode_xml(gzip.compress(_fixture("price_full.xml")))
    promo = decode_xml(gzip.compress(_fixture("promo_full.xml")))
    assert count_records("price_full", price) == 3
    # The items inside a promotion are not promotions.
    assert count_records("promo_full", promo) == 2
    assert promo.findtext(".//ClubID") == "0 - כלל הלקוחות"


def test_utf8_bom_is_dropped() -> None:
    root = decode_xml(b"\xef\xbb\xbf<Root><Item/></Root>")
    assert count_records("price_full", root) == 1


def test_records_are_counted_in_any_case_and_namespace() -> None:
    xml = b'<asx:abap xmlns:asx="urn:x"><STORES><STORE/><STORE/></STORES><asx:Store/></asx:abap>'
    assert count_records("stores", decode_xml(xml)) == 3


def test_broken_gz_raises() -> None:
    broken = gzip.compress(_fixture("price_full.xml"))[:40]
    with pytest.raises((OSError, EOFError)):
        decode_xml(broken)


def test_bad_xml_raises() -> None:
    with pytest.raises(ParseError):
        decode_xml(b"<Root><Item></Root>")


def test_bad_encoding_raises() -> None:
    with pytest.raises(UnicodeDecodeError):
        decode_xml(b"<Root>\xff\x00\xc3</Root>")


def test_dtd_is_refused() -> None:
    xml = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><r>&a;</r>'
    with pytest.raises(ValueError, match="DTD"):
        decode_xml(xml)


def test_gz_over_the_cap_after_gunzip_raises() -> None:
    data = gzip.compress(b"<Root>" + b" " * 5000 + b"</Root>")
    assert len(data) < 1000
    with pytest.raises(XmlTooLargeError):
        decode_xml(data, max_xml_bytes=1000)
    assert decode_xml(data, max_xml_bytes=10_000).tag == "Root"


def test_plain_xml_over_the_cap_raises() -> None:
    with pytest.raises(XmlTooLargeError):
        decode_xml(b"<Root>" + b" " * 100 + b"</Root>", max_xml_bytes=50)
