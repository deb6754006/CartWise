"""identity: Pydantic request/response schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
