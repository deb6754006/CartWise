"""catalog: Pydantic request/response schemas."""

import uuid

from pydantic import BaseModel


class ChainOut(BaseModel):
    id: uuid.UUID
    name: str


class ClubOut(BaseModel):
    id: uuid.UUID
    name: str
    chain_id: uuid.UUID
    chain_name: str
