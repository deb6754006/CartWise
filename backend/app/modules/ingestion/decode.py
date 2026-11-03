"""ingestion: from a downloaded file's bytes to an XML tree, the same way for every chain.

Files come gz or plain, in UTF-8 or UTF-16 (Rami Levy's and Carrefour's Stores files).
"""

import gzip
import io
import re
import unicodedata
from xml.etree.ElementTree import Element, fromstring

from app.modules.ingestion.models import FileKind

# The XML of one file, after gunzip, may not be larger than this.
MAX_XML_BYTES = 500 * 1024 * 1024

GZIP_MAGIC = b"\x1f\x8b"
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
# The official files have no DTD. Refusing one rules out entity expansion attacks.
_DTD = re.compile(r"<!DOCTYPE|<!ENTITY", re.IGNORECASE)

# The element that is one record, per kind. Matched on the local name, case-insensitively:
# chains differ in case (Shufersal's Stores file has STORE) and some use a namespace.
RECORD_TAGS: dict[FileKind, str] = {
    "stores": "Store",
    "price_full": "Item",
    "promo_full": "Promotion",
}


class XmlTooLargeError(ValueError):
    pass


def _gunzip(data: bytes, max_bytes: int) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        out = stream.read(max_bytes + 1)
    if len(out) > max_bytes:
        raise XmlTooLargeError(f"XML over {max_bytes} bytes after gunzip")
    return out


def _text(data: bytes) -> str:
    if data[:2] in _UTF16_BOMS:
        return data.decode("utf-16")  # reads, and drops, the BOM
    return data.decode("utf-8-sig")


def decode_xml(data: bytes, max_xml_bytes: int = MAX_XML_BYTES) -> Element:
    """The root element. Raises (OSError, EOFError, UnicodeDecodeError, ParseError, ValueError)
    on a broken gz, a bad encoding, bad XML or a file over the size cap."""
    if data[:2] == GZIP_MAGIC:
        data = _gunzip(data, max_xml_bytes)
    elif len(data) > max_xml_bytes:
        raise XmlTooLargeError(f"XML over {max_xml_bytes} bytes")
    text = _text(data)
    if _DTD.search(text):
        raise ValueError("XML with a DTD is not accepted")
    return fromstring(text)  # noqa: S314 (no DTD, see above; expat limits entity expansion)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def clean_text(value: str | None) -> str:
    """NFC, with runs of whitespace collapsed to one space."""
    return " ".join(unicodedata.normalize("NFC", value or "").split())


def child_fields(element: Element) -> dict[str, str]:
    """The cleaned text of each child, by lowercased local name. The first of a name wins."""
    fields: dict[str, str] = {}
    for child in element:
        if isinstance(child.tag, str):
            fields.setdefault(local_name(child.tag).lower(), clean_text(child.text))
    return fields


def count_elements(root: Element, tag: str) -> int:
    """How many elements under root (root included) have this local name, in any case."""
    wanted = tag.lower()
    return sum(
        1
        for element in root.iter()
        if isinstance(element.tag, str) and local_name(element.tag).lower() == wanted
    )


def count_records(kind: FileKind, root: Element) -> int:
    return count_elements(root, RECORD_TAGS[kind])
