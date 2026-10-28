"""Money is an integer number of agorot (1 shekel = 100 agorot)."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

type Agorot = int


def from_shekels(value: Decimal | str) -> Agorot:
    """Convert a shekel amount to agorot, rounding half up (away from zero)."""
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid money amount: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"invalid money amount: {value!r}")
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_shekels_str(agorot: Agorot) -> str:
    """Format agorot as a shekel string with two decimals, e.g. 1290 -> "12.90"."""
    sign = "-" if agorot < 0 else ""
    whole, frac = divmod(abs(agorot), 100)
    return f"{sign}{whole}.{frac:02d}"
