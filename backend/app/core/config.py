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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    DATABASE_URL: str = DEV_DATABASE_URL
    ENV: Literal["dev", "test", "prod"] = "dev"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    DEVICE_TOKEN_SECRET: str = DEV_DEVICE_TOKEN_SECRET
    DEVICE_TOKEN_TTL_DAYS: int = Field(default=30, ge=1, le=365)

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
