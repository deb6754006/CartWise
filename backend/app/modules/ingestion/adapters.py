"""ingestion: one adapter per chain, each our own code (no il-supermarket-scraper).

An adapter lists the files a chain publishes (`list_files`) and downloads one (`fetch`). Its HTTP
functions are injected, so tests never touch the network. The portals were checked on 2026-11-03
(docs/implementation-artifacts/research-3-1-chains.md).

A file URL can carry a signature (Shufersal's Azure Blob links), so a URL never goes into a log
line or an error message: urllib's own errors are re-raised without it.
"""

import html
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from http.client import HTTPException
from http.cookiejar import CookieJar
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from app.core.config import Settings
from app.modules.ingestion.models import FILE_KINDS, FileKind

USER_AGENT = "CartWise/1.0 (+https://github.com/deb6754006/CartWise)"
TIMEOUT_SECONDS = 60.0
# A downloaded file (or page) larger than this fails.
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

SHUFERSAL_GOV_CODE = "7290027600007"
RAMI_LEVY_GOV_CODE = "7290058140886"
CARREFOUR_GOV_CODE = "7290055700007"
# The chains ingested in the MVP, in scheduling order.
CHAIN_KEYS = ("shufersal", "rami_levy", "carrefour")

_PREFIX_KIND: dict[str, FileKind] = {
    "Stores": "stores",
    "PriceFull": "price_full",
    "PromoFull": "promo_full",
}
# A prefix match: what follows (a .gz or .xml suffix, say) does not matter.
_FILE_NAME = re.compile(
    r"^(Stores|PriceFull|PromoFull)(\d{13})-(\d+)(?:-(\d+))?-(\d{8})-?(\d{3,6})?"
)

_URL = re.compile(r"https?://\S+", re.IGNORECASE)

type HttpGet = Callable[[str], bytes]
type HttpPost = Callable[[str, Mapping[str, str]], bytes]


class DownloadTooLargeError(ValueError):
    pass


class HttpStatusError(OSError):
    """An HTTP error status, without the URL (it may carry a signature)."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class PortalFormatError(ValueError):
    """A portal page or listing is not in the shape the adapter expects."""


@dataclass(frozen=True, slots=True)
class RemoteFile:
    name: str
    kind: FileKind
    # None for a Stores file: it covers every store of the chain.
    store_code: str | None
    # YYYYMMDDHHMMSS, from the file name.
    stamp: str
    url: str


@dataclass(frozen=True, slots=True)
class ParsedName:
    kind: FileKind
    chain_code: str
    store_code: str | None
    stamp: str


class ChainAdapter(Protocol):
    key: str
    gov_chain_code: str
    name: str

    def list_files(self) -> list[RemoteFile]:
        """Every Stores, PriceFull and PromoFull file the portal lists now. Raises on failure."""
        ...

    def fetch(self, file: RemoteFile) -> bytes:
        """The file's bytes, as published (often gz). Raises on failure."""
        ...


def redact_urls(text: str) -> str:
    """text with every URL replaced by <url>: a URL may carry a signature."""
    return _URL.sub("<url>", text)


def parse_file_name(name: str) -> ParsedName | None:
    """The kind, store and time stamp in an official file name, or None if it is not a file kind
    the MVP ingests (partial Price and Promo files, for example)."""
    match = _FILE_NAME.match(name)
    if match is None:
        return None
    prefix, chain_code, first, second, date, time = match.groups()
    kind = _PREFIX_KIND[prefix]
    store_code = None if kind == "stores" else (f"{first}-{second}" if second else first)
    return ParsedName(kind, chain_code, store_code, date + (time or "").ljust(6, "0"))


def remote_file(name: str, url: str, chain_code: str) -> RemoteFile | None:
    """The file, or None if it is not a kind the MVP ingests or belongs to another chain."""
    parsed = parse_file_name(name)
    if parsed is None or parsed.chain_code != chain_code:
        return None
    return RemoteFile(name, parsed.kind, parsed.store_code, parsed.stamp, url)


def latest_per_store(files: Iterable[RemoteFile]) -> list[RemoteFile]:
    """The latest file of each (kind, store): the highest stamp, then the larger name.
    Sorted by kind (stores first: 3.4 needs the stores) and then by store."""
    latest: dict[tuple[FileKind, str | None], RemoteFile] = {}
    for file in files:
        key = (file.kind, file.store_code)
        current = latest.get(key)
        if current is None or (file.stamp, file.name) > (current.stamp, current.name):
            latest[key] = file
    return sorted(
        latest.values(),
        key=lambda f: (FILE_KINDS.index(f.kind), f.store_code or "", f.name),
    )


class UrllibClient:
    """GET and form POST over urllib, with a cookie jar of its own. TLS is verified as usual."""

    def __init__(
        self, timeout: float = TIMEOUT_SECONDS, max_bytes: int = MAX_DOWNLOAD_BYTES
    ) -> None:
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self._timeout = timeout
        self._max_bytes = max_bytes

    def get(self, url: str) -> bytes:
        return self._send(Request(url, headers={"User-Agent": USER_AGENT}))  # noqa: S310

    def post(self, url: str, form: Mapping[str, str]) -> bytes:
        body = urlencode(form).encode("ascii")
        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        return self._send(Request(url, data=body, headers=headers, method="POST"))  # noqa: S310

    def _send(self, request: Request) -> bytes:
        if urlsplit(request.full_url).scheme != "https":
            raise PortalFormatError("only https URLs are fetched")
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body: bytes = response.read(self._max_bytes + 1)
        except HTTPError as exc:
            exc.close()
            raise HttpStatusError(exc.code) from None
        except URLError as exc:
            # The reason is a socket or TLS error (worth keeping: a filtered network shows up
            # here as a certificate error), or a message. Any URL in it is removed.
            reason = exc.reason
            detail = f"{type(reason).__name__}: {reason}" if isinstance(reason, Exception) else ""
            raise OSError(redact_urls(detail) or "URLError") from None
        except (HTTPException, TimeoutError) as exc:
            raise OSError(type(exc).__name__) from None
        if len(body) > self._max_bytes:
            raise DownloadTooLargeError(f"download over {self._max_bytes} bytes")
        return body


def _page_text(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- Shufersal


SHUFERSAL_CATEGORY: dict[FileKind, int] = {"stores": 5, "price_full": 2, "promo_full": 4}
SHUFERSAL_CATEGORIES = tuple(SHUFERSAL_CATEGORY.values())
SHUFERSAL_MAX_PAGES = 60  # PriceFull is about 22 pages of 20 rows
_HREF = re.compile(r"""<a\s[^>]*?href\s*=\s*["'](https://[^"']+)["']""", re.IGNORECASE)


class ShufersalAdapter:
    key = "shufersal"
    gov_chain_code = SHUFERSAL_GOV_CODE
    name = "שופרסל"

    def __init__(self, base_url: str, get: HttpGet, max_pages: int = SHUFERSAL_MAX_PAGES) -> None:
        self._base = base_url.rstrip("/")
        self._get = get
        self._max_pages = max_pages

    def _page(self, category: int, page: int, store_id: int = 0) -> list[RemoteFile]:
        query = urlencode({"catID": category, "storeId": store_id, "page": page})
        text = _page_text(self._get(f"{self._base}/FileObject/UpdateCategory?{query}"))
        files = []
        for href in _HREF.findall(text):
            url = html.unescape(href)
            name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
            file = remote_file(name, url, self.gov_chain_code)
            if file is not None:
                files.append(file)
        return files

    def list_files(self) -> list[RemoteFile]:
        found: dict[str, RemoteFile] = {}
        for category in SHUFERSAL_CATEGORIES:
            for page in range(1, self._max_pages + 1):
                rows = self._page(category, page)
                new = [f for f in rows if f.name not in found]
                # A page with no rows ends the category. So does one with nothing new: a portal
                # that ignored the page number would otherwise be read max_pages times.
                if not new:
                    break
                found.update((f.name, f) for f in new)
        return list(found.values())

    def fetch(self, file: RemoteFile) -> bytes:
        """The signed links expire about 30 minutes after the listing, and listing and
        downloading take longer than that. On a 403, the file's link is asked for again, from
        its store's page, and the download is tried once more."""
        try:
            return self._get(file.url)
        except HttpStatusError as exc:
            if exc.status != 403:
                raise
            store_id = 0 if file.store_code is None else int(file.store_code.rsplit("-", 1)[-1])
            fresh = self._page(SHUFERSAL_CATEGORY[file.kind], 1, store_id)
            match = next((f for f in fresh if f.name == file.name), None)
            if match is None:
                raise
            return self._get(match.url)


# ---------------------------------------------------------------- Cerberus (Rami Levy)


_CSRF = re.compile(
    r"""<meta\s+name\s*=\s*["']csrftoken["']\s+content\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)


_LOGIN_FORM = re.compile(r"""id\s*=\s*["']login-form["']""", re.IGNORECASE)


def _csrf_token(body: bytes, where: str) -> str:
    match = _CSRF.search(_page_text(body))
    if match is None:
        raise PortalFormatError(f"no csrftoken on the {where} page")
    return html.unescape(match.group(1))


class CerberusAdapter:
    """A chain on url.publishedprices.co.il: a public user name, no password. The client's
    cookie jar keeps the session between the login, the listing and the downloads."""

    def __init__(
        self,
        key: str,
        gov_chain_code: str,
        name: str,
        base_url: str,
        username: str,
        get: HttpGet,
        post: HttpPost,
    ) -> None:
        self.key = key
        self.gov_chain_code = gov_chain_code
        self.name = name
        self._base = base_url.rstrip("/")
        self._username = username
        self._get = get
        self._post = post

    def _login(self) -> str:
        """Logs in and returns the csrftoken of the file page (a new one, not the login one)."""
        token = _csrf_token(self._get(f"{self._base}/login"), "login")
        form = {"r": "", "username": self._username, "password": "", "csrftoken": token}
        # The login redirects to /file, which carries the token for the next requests. A failed
        # login returns the login page again: it has a csrftoken too, so look for its form.
        page = self._post(f"{self._base}/login/user", form)
        if _LOGIN_FORM.search(_page_text(page)):
            raise PortalFormatError("Cerberus login failed")
        return _csrf_token(page, "file")

    def list_files(self) -> list[RemoteFile]:
        token = self._login()
        form = {
            "sEcho": "1",
            "iDisplayStart": "0",
            "iDisplayLength": "100000",
            "sSearch": "",
            "cd": "/",
            "csrftoken": token,
        }
        listing = json.loads(self._post(f"{self._base}/file/json/dir", form))
        rows = listing.get("aaData") if isinstance(listing, dict) else None
        if not isinstance(rows, list):
            raise PortalFormatError("no aaData in the file listing")
        files = []
        for row in rows:
            name = row.get("fname") if isinstance(row, dict) else None
            if not isinstance(name, str):
                continue
            file = remote_file(name, f"{self._base}/file/d/{quote(name)}", self.gov_chain_code)
            if file is not None:
                files.append(file)
        return files

    def fetch(self, file: RemoteFile) -> bytes:
        return self._get(file.url)


# ---------------------------------------------------------------- Carrefour


_CARREFOUR_PATH = re.compile(r"""const\s+path\s*=\s*["'](\d{8})["']\s*;""")
_CARREFOUR_FILES = re.compile(r"const\s+files\s*=\s*")


class CarrefourAdapter:
    key = "carrefour"
    gov_chain_code = CARREFOUR_GOV_CODE
    name = "קרפור"

    def __init__(self, base_url: str, get: HttpGet) -> None:
        self._base = base_url.rstrip("/")
        self._get = get

    def list_files(self) -> list[RemoteFile]:
        text = _page_text(self._get(f"{self._base}/"))
        path = _CARREFOUR_PATH.search(text)
        start = _CARREFOUR_FILES.search(text)
        if path is None or start is None:
            raise PortalFormatError("no path or files on the Carrefour page")
        try:
            entries, _ = json.JSONDecoder().raw_decode(text, start.end())
        except json.JSONDecodeError:
            raise PortalFormatError("the Carrefour files list is not JSON") from None
        if not isinstance(entries, list):
            raise PortalFormatError("the Carrefour files list is not a list")
        files = []
        for entry in entries:
            name = entry.get("name") if isinstance(entry, dict) else None
            if not isinstance(name, str):
                continue
            url = f"{self._base}/{path.group(1)}/{quote(name)}"
            file = remote_file(name, url, self.gov_chain_code)
            if file is not None:
                files.append(file)
        return files

    def fetch(self, file: RemoteFile) -> bytes:
        return self._get(file.url)


def build_adapters(
    settings: Settings, client_factory: Callable[[], UrllibClient] = UrllibClient
) -> dict[str, ChainAdapter]:
    """One adapter per chain, keyed by CHAIN_KEYS, each with an HTTP client (and cookies) of its
    own. Tests pass a client_factory of fakes."""
    shufersal, rami_levy, carrefour = client_factory(), client_factory(), client_factory()
    adapters: list[ChainAdapter] = [
        ShufersalAdapter(settings.SHUFERSAL_PRICES_URL, shufersal.get),
        CerberusAdapter(
            "rami_levy",
            RAMI_LEVY_GOV_CODE,
            "רמי לוי",
            settings.CERBERUS_URL,
            settings.CERBERUS_RAMI_LEVY_USERNAME,
            rami_levy.get,
            rami_levy.post,
        ),
        CarrefourAdapter(settings.CARREFOUR_PRICES_URL, carrefour.get),
    ]
    return {adapter.key: adapter for adapter in adapters}
