"""admin: Pydantic request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AdminAliasOut(BaseModel):
    id: uuid.UUID
    chain_id: uuid.UUID
    chain_name: str
    alias_text: str
    barcode: str | None
    product_id: uuid.UUID | None
    product_name: str | None
    confidence: float | None
    occurrences: int
    updated_at: datetime


class ProductVotesOut(BaseModel):
    product_id: uuid.UUID
    product_name: str | None
    votes: int


class DisputedMatchOut(BaseModel):
    alias: AdminAliasOut
    # The counted votes of users for each product, the most first.
    votes: list[ProductVotesOut]


class DisputedMatchesOut(BaseModel):
    total: int
    items: list[DisputedMatchOut]


class CandidateOut(BaseModel):
    product_id: uuid.UUID
    product_name: str | None
    score: float


class UncertainMatchOut(BaseModel):
    alias: AdminAliasOut
    # Up to 3, the best first.
    candidates: list[CandidateOut]


class UncertainMatchesOut(BaseModel):
    total: int
    items: list[UncertainMatchOut]


class ProposedProductOut(BaseModel):
    id: uuid.UUID
    name: str
    barcode: str | None
    created_at: datetime
    alias_count: int


class ProposedProductsOut(BaseModel):
    total: int
    items: list[ProposedProductOut]


class ApproveMatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Omitted: the alias's current product.
    product_id: uuid.UUID | None = None


class ApproveMatchOut(BaseModel):
    alias_id: uuid.UUID
    state: str
    product_id: uuid.UUID | None
    changed: bool
    # The chain's other final aliases of the same text, moved to the same product.
    realigned_alias_ids: list[uuid.UUID]


class ApproveProductOut(BaseModel):
    product_id: uuid.UUID
    status: str
    changed: bool


class MergeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keep_id: uuid.UUID
    remove_id: uuid.UUID


class MergeOut(BaseModel):
    keep_id: uuid.UUID
    remove_id: uuid.UUID
    remove_status: str
    aliases_moved: int
    barcode_moved: bool
    observations_moved: int
    promotion_products_moved: int
    votes_moved: int
    candidates_removed: int
