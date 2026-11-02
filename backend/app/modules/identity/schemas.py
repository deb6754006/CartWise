"""identity: Pydantic request/response schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.models import TravelMinutes, TravelMode


class DeviceRegisterIn(BaseModel):
    # Lone surrogates are rejected by pydantic itself (string_unicode -> 422), so the
    # value is always encodable as UTF-8 for hashing.
    install_id: str = Field(min_length=16, max_length=128)


class DeviceRegisterOut(BaseModel):
    device_id: uuid.UUID
    device_token: str
    expires_at: datetime


class MeOut(BaseModel):
    kind: Literal["user", "device"]
    id: uuid.UUID


class LinkIn(BaseModel):
    # The guest's device token. Omitted: the user is created or found, no device is linked.
    device_token: str | None = Field(default=None, min_length=1, max_length=4096)


class LinkOut(BaseModel):
    user_id: uuid.UUID


class ClubIdsIn(BaseModel):
    # extra="forbid": a member number (or anything else) is rejected, not silently dropped.
    model_config = ConfigDict(extra="forbid")

    club_ids: list[uuid.UUID] = Field(max_length=200)


class ClubIdsOut(BaseModel):
    club_ids: list[uuid.UUID]


class BrandIdsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_ids: list[uuid.UUID] = Field(max_length=200)


class MyBrandOut(BaseModel):
    id: uuid.UUID
    name: str


class MyBrandsOut(BaseModel):
    # With names, unlike clubs: the app has no full list of brands to look them up in.
    brands: list[MyBrandOut]


class PrefsIn(BaseModel):
    # extra="forbid": a location (or anything else) is rejected, not silently dropped.
    model_config = ConfigDict(extra="forbid")

    default_mode: TravelMode
    default_minutes: TravelMinutes


class PrefsOut(BaseModel):
    default_mode: TravelMode
    default_minutes: TravelMinutes
