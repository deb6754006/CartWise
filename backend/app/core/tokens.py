"""Device tokens for guests (AD-12): HS256 JWTs signed with DEVICE_TOKEN_SECRET.

Claims: sub (device_id), typ ("device"), iat, exp. Tokens are never logged.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings
from app.core.errors import AppError

ALGORITHM = "HS256"
DEVICE_TYP = "device"
INVALID_CREDENTIALS_HE = "ההתחברות לא תקפה, נסו שוב"


def invalid_token() -> AppError:
    return AppError("invalid_token", INVALID_CREDENTIALS_HE, status=401)


def issue_device_token(device_id: uuid.UUID) -> tuple[str, datetime]:
    """Sign a device token. Returns (token, expires_at in UTC)."""
    settings = get_settings()
    now = datetime.now(UTC).replace(microsecond=0)
    expires_at = now + timedelta(days=settings.DEVICE_TOKEN_TTL_DAYS)
    claims = {
        "sub": str(device_id),
        "typ": DEVICE_TYP,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(claims, settings.DEVICE_TOKEN_SECRET, algorithm=ALGORITHM)
    return token, expires_at


def decode_device_token(token: str) -> uuid.UUID:
    """Verify a device token and return its device_id. Raises AppError 401 invalid_token."""
    try:
        claims = jwt.decode(
            token,
            get_settings().DEVICE_TOKEN_SECRET,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "typ", "iat", "exp"]},
        )
    except jwt.PyJWTError:
        raise invalid_token() from None
    if claims.get("typ") != DEVICE_TYP:
        raise invalid_token()
    try:
        return uuid.UUID(str(claims["sub"]))
    except ValueError:
        raise invalid_token() from None
