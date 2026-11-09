"""ingestion: a store's PriceFull and PromoFull files, to products (through catalog) and to price
observations and promotions (through pricing).

Both files have a root whose children are ChainID, SubChainID and StoreID, and then Items > Item
or Promotions > Promotion. Tags are matched on their local name in any case. Times in the files
are local (Asia/Jerusalem), with no zone.

An item with a barcode (ItemType 1, 8 to 14 digits) is matched to the product with that barcode,
which is created if missing, and its name is saved as the chain's alias of it (matching.service).
An item with an internal code (ItemType 0, or no valid barcode) is matched by its name
(matching.service.match_file_items, Story 3.6), and priced when it gets a product.
No product name or price ever goes into a log line.
"""

import logging
import re
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.money import from_shekels
from app.modules.catalog import service as catalog_service
from app.modules.catalog.models import PackUnit
from app.modules.catalog.service import ProductRecord
from app.modules.ingestion.decode import child_fields, local_name
from app.modules.matching import service as matching_service
from app.modules.matching.service import FileItem
from app.modules.pricing import service as pricing_service
from app.modules.pricing.models import PricePer, PromotionKind
from app.modules.pricing.service import OfficialPrice, PromotionRecord

logger = logging.getLogger("app.ingestion")

LOCAL_ZONE = ZoneInfo("Asia/Jerusalem")
BARCODE_ITEM_TYPE = "1"
_DIGITS = re.compile(r"[0-9]+")
# unit_price_agorot and bundle_price_agorot are integers.
MAX_AGOROT = 2**31 - 1
# Geresh, gershayim and quotation marks, dropped before a UnitQty is looked up ('ק"ג' -> 'קג').
_UNIT_QUOTES = str.maketrans("", "", "'\"`׳״‘’“”")
_PACK_UNITS: dict[str, PackUnit] = {
    "גרם": "g",
    "קילוגרם": "kg",
    "קג": "kg",
    "מיליליטר": "ml",
    "מל": "ml",
    "ליטר": "l",
    "יחידה": "unit",
    "יח": "unit",
}
_EVERYONE_PREFIX = "0 - כלל הלקוחות"
REWARD_MULTI_BUY = "10"
REWARD_PERCENT = "2"
REWARD_FIXED_PRICE = "3"
# A handler gets the tree, not the file: the service stamps the file name on the root under this
# attribute (namespaced, so no file's own attribute is taken for it).
SOURCE_REF_ATTRIBUTE = "{urn:cartwise}source-file"


class UnknownStoreError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PriceItem:
    barcode: str
    name: str
    pack_size: Decimal | None
    pack_unit: PackUnit | None
    is_weighted: bool
    price_agorot: int
    per: PricePer
    observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class InternalItem:
    """An item with no barcode (an internal code), matched by its name."""

    name: str
    price_agorot: int
    per: PricePer
    is_weighted: bool
    pack_size: Decimal | None
    pack_unit: PackUnit | None
    observed_at: datetime | None


@dataclass(slots=True)
class PriceFile:
    store_code: str
    items: list[PriceItem]
    internal_items: list[InternalItem] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True, slots=True)
class PromoItem:
    barcode: str | None
    reward_type: str
    min_qty: Decimal | None
    discount_rate: Decimal | None
    discounted_price_agorot: int | None


@dataclass(frozen=True, slots=True)
class PromoEntry:
    gov_promotion_id: str
    description: str
    club: str
    is_coupon: bool
    starts_at: datetime | None
    ends_at: datetime | None
    items: tuple[PromoItem, ...]


@dataclass(slots=True)
class PromoFile:
    store_code: str
    promotions: list[PromoEntry]
    skipped: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True, slots=True)
class Reward:
    kind: PromotionKind
    min_qty: Decimal
    bundle_price_agorot: int | None
    percent: Decimal | None


def local_to_utc(value: str) -> datetime | None:
    """A local time from a file ('2026-11-01T00:00:00.000', '2026-11-01 08:30:00', ...) in UTC.
    One with a zone is taken in its zone. None when there is no valid time."""
    text = value.strip().replace("/", "-")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=LOCAL_ZONE)
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        # Not a time, or one too close to datetime.min or max to move to UTC.
        return None


def club_is_everyone(club: str) -> bool:
    """Only exactly '0', or '0 - כלל הלקוחות...', is for every customer. Anything else, empty or
    an expression with | or & included, may be for a club only."""
    text = " ".join(club.split())
    return text == "0" or text.startswith(_EVERYONE_PREFIX)


def pack_unit(unit_qty: str) -> PackUnit | None:
    return _PACK_UNITS.get("".join(unit_qty.translate(_UNIT_QUOTES).split()))


def _decimal(value: str) -> Decimal | None:
    """A finite number, or None."""
    try:
        number = Decimal(value.strip())
    except (InvalidOperation, ArithmeticError):
        return None
    return number if number.is_finite() else None


def _agorot(value: str) -> int | None:
    """A positive shekel amount in agorot (rounded half up), or None."""
    if not value.strip():
        return None
    try:
        agorot = from_shekels(value.strip())
    except (ValueError, ArithmeticError):
        # Not a number, or one too large to quantize (1e30, 1E+999999).
        return None
    return agorot if 0 < agorot <= MAX_AGOROT else None


def barcode_of(fields: dict[str, str]) -> str | None:
    """The barcode of an item: ItemType 1 and a valid barcode (catalog.service.valid_barcode)."""
    if fields.get("itemtype", "") != BARCODE_ITEM_TYPE:
        return None
    return catalog_service.valid_barcode(fields.get("itemcode", ""))


def _store_code(root: Element) -> str:
    code = child_fields(root).get("storeid", "")
    if not _DIGITS.fullmatch(code):
        raise UnknownStoreError(f"unknown store {code[:32]}")
    return code.lstrip("0") or "0"


def _elements(root: Element, tag: str) -> list[Element]:
    return [
        element
        for element in root.iter()
        if isinstance(element.tag, str) and local_name(element.tag).lower() == tag
    ]


def parse_price_file(root: Element) -> PriceFile:
    """The store's code and its items with a valid price and a name, in file order: those with a
    barcode in items (the first item of a barcode wins), and those with none in internal_items
    (the first of an alias key wins, counted after as duplicate_name). Skipped items are counted
    by reason."""
    result = PriceFile(store_code=_store_code(root), items=[])
    seen: set[str] = set()
    seen_internal: set[str] = set()
    for element in _elements(root, "item"):
        fields = child_fields(element)
        barcode = barcode_of(fields)
        price = _agorot(fields.get("itemprice", ""))
        if price is None:
            result.skipped["bad_price"] += 1
            continue
        name = fields.get("itemname", "")
        if not name:
            result.skipped["no_name"] += 1
            continue
        if barcode is not None and barcode in seen:
            result.skipped["duplicate"] += 1
            continue
        # An item with no barcode is known by its name, under the key its alias will have. One
        # with no key is kept: matching gives it no product.
        key = catalog_service.alias_norm(name) if barcode is None else None
        if key is not None and key in seen_internal:
            result.skipped["duplicate_name"] += 1
            continue
        unit = pack_unit(fields.get("unitqty", ""))
        size = _decimal(fields.get("quantity", ""))
        has_pack = unit is not None and size is not None and size > 0
        weighted = fields.get("bisweighted", "") == "1"
        per: PricePer = "kg" if weighted else "unit"
        observed_at = local_to_utc(fields.get("priceupdatetime", ""))
        if barcode is None:
            if key is not None:
                seen_internal.add(key)
            result.internal_items.append(
                InternalItem(
                    name=name,
                    price_agorot=price,
                    per=per,
                    is_weighted=weighted,
                    pack_size=size if has_pack else None,
                    pack_unit=unit if has_pack else None,
                    observed_at=observed_at,
                )
            )
            continue
        seen.add(barcode)
        result.items.append(
            PriceItem(
                barcode=barcode,
                name=name,
                pack_size=size if has_pack else None,
                pack_unit=unit if has_pack else None,
                is_weighted=weighted,
                price_agorot=price,
                per=per,
                observed_at=observed_at,
            )
        )
    return result


def _promo_time(fields: dict[str, str], name: str) -> datetime | None:
    """PromotionStartDateTime, or else PromotionStartDate with PromotionStartHour."""
    combined = fields.get(f"promotion{name}datetime", "")
    if not combined:
        date = fields.get(f"promotion{name}date", "")
        combined = f"{date} {fields.get(f'promotion{name}hour', '')}".strip() if date else ""
    return local_to_utc(combined)


def _promo_item(element: Element, promotion: dict[str, str]) -> PromoItem:
    # The reward is the item's; a file that has it on the promotion gives it there.
    fields = child_fields(element)

    def get(name: str) -> str:
        return fields.get(name) or promotion.get(name, "")

    min_qty = get("minqty")
    rate = get("discountrate")
    return PromoItem(
        barcode=barcode_of(fields),
        reward_type=get("rewardtype"),
        min_qty=_decimal(min_qty) if min_qty else None,
        discount_rate=_decimal(rate) if rate else None,
        discounted_price_agorot=_agorot(get("discountedprice")),
    )


def parse_promo_file(root: Element) -> PromoFile:
    """The store's code and its promotions, in file order. The first of an id wins."""
    result = PromoFile(store_code=_store_code(root), promotions=[])
    seen: set[str] = set()
    for element in _elements(root, "promotion"):
        fields = child_fields(element)
        gov_id = fields.get("promotionid", "")
        if not gov_id:
            result.skipped["no_id"] += 1
            continue
        if gov_id in seen:
            result.skipped["duplicate"] += 1
            continue
        seen.add(gov_id)
        result.promotions.append(
            PromoEntry(
                gov_promotion_id=gov_id,
                description=fields.get("promotiondescription", ""),
                club=fields.get("clubid", ""),
                is_coupon=fields.get("additionaliscoupon", "") == "1",
                starts_at=_promo_time(fields, "start"),
                ends_at=_promo_time(fields, "end"),
                items=tuple(
                    _promo_item(item, fields) for item in _elements(element, "promotionitem")
                ),
            )
        )
    return result


def promotion_reward(item: PromoItem) -> Reward | None:
    """The kind of a promotion, from its first item that has a product. None: not saved."""
    price = item.discounted_price_agorot
    min_qty = item.min_qty
    rate = item.discount_rate
    if item.reward_type == REWARD_PERCENT and rate is not None and 0 < rate <= 100:
        # The rate is what applies: each item's DiscountedPrice is its own, so none is kept.
        return Reward("percent", Decimal(1), None, rate)
    if item.reward_type == REWARD_MULTI_BUY or (min_qty is not None and min_qty > 1):
        if price is None:
            return None
        quantity = min_qty if min_qty is not None and min_qty > 0 else Decimal(1)
        return Reward("multi_buy", quantity, price, None)
    if price is not None:
        # RewardType 3, or any other with a price for one (MinQty such as 0.010 by weight).
        return Reward("fixed_price", Decimal(1), price, None)
    return None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _store_id(session: Session, chain_id: uuid.UUID, code: str) -> uuid.UUID:
    store_id = catalog_service.store_id_by_code(session, chain_id, code)
    if store_id is None:
        raise UnknownStoreError(f"unknown store {code}")
    return store_id


type FileHandler = Callable[[Session, uuid.UUID, Element], int]


def _log(event: str, skipped: Counter[str], **counts: int) -> None:
    log = logger.warning if skipped else logger.info
    log(event, extra={**counts, **{f"skipped_{reason}": n for reason, n in skipped.items()}})


def price_handler(now: Callable[[], datetime] = _utcnow) -> FileHandler:
    """The handler of PriceFull files. Returns the items handled: new observations and unchanged
    prices together."""

    def handle(session: Session, chain_id: uuid.UUID, root: Element) -> int:
        at = now()
        parsed = parse_price_file(root)
        store_id = _store_id(session, chain_id, parsed.store_code)
        product_ids = catalog_service.ensure_products_by_barcode(
            session,
            (
                ProductRecord(i.barcode, i.name, i.pack_size, i.pack_unit, i.is_weighted)
                for i in parsed.items
            ),
            now=at,
        )
        aliases_new = matching_service.match_barcodes(
            session,
            chain_id,
            ((i.name, i.barcode) for i in parsed.items),
            now=at,
            product_ids=product_ids,
        )
        # Items with no barcode: by their name. The price is a hint only per unit (the medians
        # it is tested against are per unit).
        internal_ids = matching_service.match_file_items(
            session,
            chain_id,
            [
                FileItem(
                    i.name,
                    i.price_agorot if i.per == "unit" else None,
                    is_weighted=i.is_weighted,
                    pack_size=i.pack_size,
                    pack_unit=i.pack_unit,
                )
                for i in parsed.internal_items
            ],
            now=at,
        )

        def official(product_id: uuid.UUID, item: PriceItem | InternalItem) -> OfficialPrice:
            return OfficialPrice(
                product_id=product_id,
                unit_price_agorot=item.price_agorot,
                per=item.per,
                # A time in the future is a clock mistake: it would hide later prices.
                observed_at=min(item.observed_at, at) if item.observed_at else at,
            )

        prices = [official(product_ids[item.barcode], item) for item in parsed.items]
        # One price per product: the items with a barcode come first, and the first one wins.
        priced = {p.product_id for p in prices}
        internal_priced = internal_unmatched = internal_same_product = 0
        for item, product_id in zip(parsed.internal_items, internal_ids, strict=True):
            if product_id is None:
                internal_unmatched += 1
            elif product_id in priced:
                internal_same_product += 1
            else:
                priced.add(product_id)
                prices.append(official(product_id, item))
                internal_priced += 1
        new, unchanged = pricing_service.record_official_prices(
            session, store_id, chain_id, prices, root.get(SOURCE_REF_ATTRIBUTE) or None, at
        )
        _log(
            "ingestion_prices",
            parsed.skipped,
            items=len(parsed.items),
            internal=len(parsed.internal_items),
            internal_priced=internal_priced,
            internal_unmatched=internal_unmatched,
            internal_same_product=internal_same_product,
            observations_new=new,
            unchanged=unchanged,
            aliases_new=aliases_new,
        )
        return new + unchanged

    return handle


def build_promotions(
    session: Session,
    chain_id: uuid.UUID,
    entries: Sequence[PromoEntry],
    at: datetime,
    skipped: Counter[str],
) -> list[PromotionRecord]:
    """The promotions to save, out of the file's. Each one skipped is counted in skipped."""
    product_ids = catalog_service.product_ids_by_barcode(
        session, (i.barcode for e in entries for i in e.items if i.barcode is not None)
    )
    chain_club: uuid.UUID | None = None
    records: list[PromotionRecord] = []
    for entry in entries:
        if entry.is_coupon:
            skipped["coupon"] += 1
            continue
        if entry.ends_at is None:
            skipped["no_end"] += 1
            continue
        if entry.ends_at <= at:
            skipped["expired"] += 1
            continue
        starts_at = entry.starts_at or at
        if entry.ends_at <= starts_at:
            skipped["bad_dates"] += 1
            continue
        with_product = [i for i in entry.items if i.barcode in product_ids]
        if not with_product:
            skipped["no_product"] += 1
            continue
        reward = promotion_reward(with_product[0])
        if reward is None:
            skipped["no_reward"] += 1
            continue
        # A promotion can mix rewards: only the items with the first one's are kept.
        same = [i for i in with_product if promotion_reward(i) == reward]
        if len(same) < len(with_product):
            skipped["mixed_reward_items"] += len(with_product) - len(same)
            with_product = same
        club_id: uuid.UUID | None = None
        if not club_is_everyone(entry.club):
            if chain_club is None:
                chain_club = catalog_service.ensure_chain_club(session, chain_id)
            club_id = chain_club
        records.append(
            PromotionRecord(
                gov_promotion_id=entry.gov_promotion_id,
                description=entry.description,
                club_id=club_id,
                kind=reward.kind,
                min_qty=reward.min_qty,
                bundle_price_agorot=reward.bundle_price_agorot,
                percent=reward.percent,
                starts_at=starts_at,
                ends_at=entry.ends_at,
                product_ids=frozenset(
                    product_ids[i.barcode] for i in with_product if i.barcode is not None
                ),
            )
        )
    return records


def promo_handler(now: Callable[[], datetime] = _utcnow) -> FileHandler:
    """The handler of PromoFull files: the store's full picture. Returns the promotions saved."""

    def handle(session: Session, chain_id: uuid.UUID, root: Element) -> int:
        at = now()
        parsed = parse_promo_file(root)
        store_id = _store_id(session, chain_id, parsed.store_code)
        records = build_promotions(session, chain_id, parsed.promotions, at, parsed.skipped)
        if not records and parsed.skipped["no_product"]:
            # The store's prices are not in yet (its PriceFull failed, or the store is new).
            # Failing the file keeps its promotions as they are, and it is taken again next run.
            raise ValueError("no promotion matched a known product")
        saved = pricing_service.replace_store_promotions(session, store_id, chain_id, records, at)
        _log(
            "ingestion_promotions",
            parsed.skipped,
            promotions=len(parsed.promotions),
            saved=saved,
        )
        return saved

    return handle
