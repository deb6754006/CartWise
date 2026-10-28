"""Application settings, loaded from environment variables.

Defaults are for local dev only.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_DATABASE_URL = "postgresql+psycopg://cartwise:cartwise@localhost:5432/cartwise"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    DATABASE_URL: str = DEV_DATABASE_URL
    ENV: Literal["dev", "test", "prod"] = "dev"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @model_validator(mode="after")
    def _no_dev_db_in_prod(self) -> Self:
        if self.ENV == "prod" and self.DATABASE_URL == DEV_DATABASE_URL:
            raise ValueError("DATABASE_URL must be set explicitly when ENV=prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
