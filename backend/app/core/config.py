"""Application settings, loaded from environment variables.

Defaults are for local dev only.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_DATABASE_URL = "postgresql+psycopg://cartwise:cartwise@localhost:5432/cartwise"
# Minimum DEVICE_TOKEN_SECRET length when ENV=prod (HS256 key strength).
MIN_PROD_SECRET_LEN = 32
# Dev/test only, not a secret. Rejected when ENV=prod.
DEV_DEVICE_TOKEN_SECRET = "cartwise-dev-only-device-token-signing-key"  # noqa: S105
# Public JWKS of the Firebase Auth ID-token signer (securetoken@system.gserviceaccount.com).
DEFAULT_FIREBASE_JWKS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
)
DEFAULT_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# The chains' official price portals (Story 3.1). Open to anyone; no key and no account.
DEFAULT_SHUFERSAL_PRICES_URL = "https://prices.shufersal.co.il"
DEFAULT_CERBERUS_URL = "https://url.publishedprices.co.il"
DEFAULT_CARREFOUR_PRICES_URL = "https://prices.carrefour.co.il"
# Rami Levy's public user name on the Cerberus portal (no password). Not a secret.
DEFAULT_CERBERUS_RAMI_LEVY_USERNAME = "RamiLevi"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    DATABASE_URL: str = DEV_DATABASE_URL
    ENV: Literal["dev", "test", "prod"] = "dev"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    DEVICE_TOKEN_SECRET: str = DEV_DEVICE_TOKEN_SECRET
    DEVICE_TOKEN_TTL_DAYS: int = Field(default=30, ge=1, le=365)
    # Firebase project whose ID tokens are accepted (aud / iss). Empty is allowed in every
    # ENV, prod included: Google sign-in is then unavailable (503 auth_unavailable on
    # /v1/auth/link and on Firebase tokens), while guests with device tokens keep working.
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_JWKS_URL: str = DEFAULT_FIREBASE_JWKS_URL
    # Where an address entered in the app is located. Free, with no key and no account.
    NOMINATIM_URL: str = DEFAULT_NOMINATIM_URL
    # Price-file ingestion (Epic 3): where each chain publishes, and how often the worker looks.
    SHUFERSAL_PRICES_URL: str = DEFAULT_SHUFERSAL_PRICES_URL
    CERBERUS_URL: str = DEFAULT_CERBERUS_URL
    CARREFOUR_PRICES_URL: str = DEFAULT_CARREFOUR_PRICES_URL
    CERBERUS_RAMI_LEVY_USERNAME: str = DEFAULT_CERBERUS_RAMI_LEVY_USERNAME
    # Every chain is ingested at least this often (at most every 6 hours).
    INGEST_INTERVAL_HOURS: int = Field(default=6, ge=1, le=6)

    @model_validator(mode="after")
    def _no_dev_db_in_prod(self) -> Self:
        if self.ENV == "prod" and self.DATABASE_URL == DEV_DATABASE_URL:
            raise ValueError("DATABASE_URL must be set explicitly when ENV=prod")
        return self

    @model_validator(mode="after")
    def _no_dev_token_secret_in_prod(self) -> Self:
        if self.ENV != "prod":
            return self
        secret = self.DEVICE_TOKEN_SECRET.strip()
        if secret == DEV_DEVICE_TOKEN_SECRET or len(secret) < MIN_PROD_SECRET_LEN:
            raise ValueError(
                "DEVICE_TOKEN_SECRET must be set explicitly when ENV=prod "
                f"(at least {MIN_PROD_SECRET_LEN} characters)"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
