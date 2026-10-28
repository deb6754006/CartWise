"""Firebase ID-token verification (AD-12), behind a port so tests never touch the network.

Only the `sub` claim (the firebase_uid) leaves this module. Name, email, phone, picture and
every other claim are dropped here and never stored or logged. Tokens are never logged.
"""

import threading
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Protocol

import jwt
from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.tokens import invalid_token

ALGORITHM = "RS256"
ISSUER_PREFIX = "https://securetoken.google.com/"
# Clock skew tolerated for exp / iat (seconds).
LEEWAY_SECONDS = 30
MAX_UID_LEN = 128
# An unknown kid forces at most one JWKS refetch per this many seconds; other unknown kids
# in the window are rejected from the cached set (random-kid tokens cannot hammer Google).
FORCED_REFRESH_INTERVAL_SECONDS = 60.0
AUTH_UNAVAILABLE_HE = "ההתחברות עדיין לא הוגדרה"


def auth_unavailable() -> AppError:
    return AppError("auth_unavailable", AUTH_UNAVAILABLE_HE, status=503)


class FirebaseVerifier(Protocol):
    @property
    def configured(self) -> bool:
        """False when FIREBASE_PROJECT_ID is empty (Google sign-in unavailable)."""
        ...

    def verify(self, id_token: str) -> str:
        """Return the firebase_uid of a valid ID token.

        Raises AppError 401 invalid_token, or 503 auth_unavailable when not configured.
        """
        ...


class SigningKeySource(Protocol):
    """PyJWKClient's interface: the signing keys, cached unless refresh=True."""

    def get_signing_keys(self, refresh: bool = False) -> list[jwt.PyJWK]: ...


class JwksFirebaseVerifier:
    """RS256 against Firebase's public JWKS (cached), plus aud/iss/exp/iat/auth_time/sub."""

    def __init__(
        self,
        project_id: str,
        jwks_url: str,
        key_source: SigningKeySource | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.project_id = project_id.strip()
        self._keys: SigningKeySource | None = key_source
        self._jwks_url = jwks_url
        self._clock = clock
        self._last_forced_refresh: float | None = None
        self._refresh_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.project_id)

    def _key_source(self) -> SigningKeySource:
        if self._keys is None:
            # The JWK set is cached for an hour (Google rotates keys every few hours and
            # publishes them well before use). Forced refreshes are throttled below.
            self._keys = jwt.PyJWKClient(self._jwks_url, lifespan=3600, timeout=5)
        return self._keys

    def _may_force_refresh(self) -> bool:
        with self._refresh_lock:
            now = self._clock()
            last = self._last_forced_refresh
            if last is not None and now - last < FORCED_REFRESH_INTERVAL_SECONDS:
                return False
            self._last_forced_refresh = now
            return True

    def _signing_key(self, kid: str) -> jwt.PyJWK:
        """The key for kid. Unknown kid: 401. JWKS unreachable or unparseable: 503."""
        source = self._key_source()
        try:
            keys = source.get_signing_keys()
            match = next((k for k in keys if k.key_id == kid), None)
            if match is None and self._may_force_refresh():
                keys = source.get_signing_keys(refresh=True)
                match = next((k for k in keys if k.key_id == kid), None)
        except (jwt.PyJWTError, ValueError):
            # Unreachable, not JSON (e.g. a proxy page), or no usable keys: an outage on
            # Google's side (or ours), not a bad token.
            raise auth_unavailable() from None
        if match is None:
            raise invalid_token()
        return match

    def verify(self, id_token: str) -> str:
        if not self.configured:
            raise auth_unavailable()
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError:
            raise invalid_token() from None
        if header.get("alg") != ALGORITHM or not header.get("kid"):
            raise invalid_token()
        signing_key = self._signing_key(str(header["kid"]))
        try:
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=[ALGORITHM],
                audience=self.project_id,
                issuer=ISSUER_PREFIX + self.project_id,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "sub", "aud", "iss", "auth_time"]},
            )
        except jwt.PyJWTError:
            raise invalid_token() from None
        # Firebase: auth_time (when the user signed in) must be in the past.
        auth_time = claims.get("auth_time")
        if (
            not isinstance(auth_time, int | float)
            or isinstance(auth_time, bool)
            or auth_time > time.time() + LEEWAY_SECONDS
        ):
            raise invalid_token()
        uid = claims.get("sub")
        if not isinstance(uid, str) or not uid.strip() or len(uid) > MAX_UID_LEN:
            raise invalid_token()
        return uid


@lru_cache(maxsize=4)
def _verifier_for(project_id: str, jwks_url: str) -> JwksFirebaseVerifier:
    return JwksFirebaseVerifier(project_id, jwks_url)


def get_firebase_verifier(
    settings: Annotated[Settings, Depends(get_settings)],
) -> FirebaseVerifier:
    """FastAPI dependency; tests override it with a fake verifier."""
    return _verifier_for(settings.FIREBASE_PROJECT_ID, settings.FIREBASE_JWKS_URL)
