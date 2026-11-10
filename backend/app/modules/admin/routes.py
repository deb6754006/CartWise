"""admin: HTTP routes of the match admin tool (Story 4.5), for operators only (require_operator).
Calls the owning modules' services, never a repository."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import require_operator
from app.core.db import get_session
from app.modules.admin.schemas import (
    AdminAliasOut,
    ApproveMatchIn,
    ApproveMatchOut,
    ApproveProductOut,
    CandidateOut,
    DisputedMatchesOut,
    DisputedMatchOut,
    MergeIn,
    MergeOut,
    ProductVotesOut,
    ProposedProductOut,
    ProposedProductsOut,
    UncertainMatchesOut,
    UncertainMatchOut,
)
from app.modules.catalog import service as catalog_service
from app.modules.catalog.service import AdminAlias
from app.modules.matching import service as matching_service

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

_AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "No token: auth_required"},
    403: {"description": "Not an operator (or a device token): forbidden"},
    503: {"description": "Sign-in not configured: auth_unavailable"},
}

router = APIRouter(prefix="/admin", tags=["admin"], responses=_AUTH_RESPONSES)

Operator = Annotated[uuid.UUID, Depends(require_operator)]
Db = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]


def _alias(alias: AdminAlias) -> AdminAliasOut:
    return AdminAliasOut(
        id=alias.id,
        chain_id=alias.chain_id,
        chain_name=alias.chain_name,
        alias_text=alias.alias_text,
        barcode=alias.barcode,
        product_id=alias.product_id,
        product_name=alias.product_name,
        confidence=float(alias.confidence) if alias.confidence is not None else None,
        occurrences=alias.occurrences,
        updated_at=alias.updated_at,
    )


@router.get("/matches/disputed")
def disputed(
    _operator: Operator, session: Db, limit: Limit = DEFAULT_LIMIT, offset: Offset = 0
) -> DisputedMatchesOut:
    """Disputed matches, the oldest first, with the counted votes for each product."""
    total, items = matching_service.disputed_matches(session, limit, offset)
    return DisputedMatchesOut(
        total=total,
        items=[
            DisputedMatchOut(
                alias=_alias(item.alias),
                votes=[
                    ProductVotesOut(
                        product_id=v.product_id, product_name=v.product_name, votes=v.votes
                    )
                    for v in item.votes
                ],
            )
            for item in items
        ],
    )


@router.get("/matches/uncertain")
def uncertain(
    _operator: Operator, session: Db, limit: Limit = DEFAULT_LIMIT, offset: Offset = 0
) -> UncertainMatchesOut:
    """Uncertain matches, the most seen first, with up to 3 candidates each."""
    total, items = matching_service.uncertain_matches(session, limit, offset)
    return UncertainMatchesOut(
        total=total,
        items=[
            UncertainMatchOut(
                alias=_alias(item.alias),
                candidates=[
                    CandidateOut(
                        product_id=c.product_id, product_name=c.product_name, score=c.score
                    )
                    for c in item.candidates
                ],
            )
            for item in items
        ],
    )


@router.get("/products/proposed")
def proposed(
    _operator: Operator, session: Db, limit: Limit = DEFAULT_LIMIT, offset: Offset = 0
) -> ProposedProductsOut:
    """New products waiting for an operator, the oldest first."""
    total, items = catalog_service.proposed_products(session, limit, offset)
    return ProposedProductsOut(
        total=total,
        items=[
            ProposedProductOut(
                id=p.id,
                name=p.name,
                barcode=p.barcode,
                created_at=p.created_at,
                alias_count=p.alias_count,
            )
            for p in items
        ],
    )


@router.post(
    "/matches/{alias_id}/approve",
    responses={
        404: {"description": "alias_not_found"},
        422: {"description": "invalid_vote: no such product, or one merged into another"},
    },
)
def approve_match(
    alias_id: uuid.UUID,
    operator: Operator,
    session: Db,
    body: Annotated[ApproveMatchIn | None, Body()] = None,
) -> ApproveMatchOut:
    """The match is final at once (FR-39), for product_id or the alias's current product. The
    chain's other final aliases of the same text move with it."""
    product_id = body.product_id if body is not None else None
    approval = matching_service.operator_approve_match(session, alias_id, operator, product_id)
    session.commit()
    outcome = approval.outcome
    return ApproveMatchOut(
        alias_id=outcome.alias_id,
        state=outcome.state,
        product_id=outcome.product_id,
        changed=outcome.changed,
        realigned_alias_ids=list(approval.realigned_alias_ids),
    )


@router.post(
    "/products/{product_id}/approve",
    responses={
        404: {"description": "product_not_found"},
        409: {"description": "product_merged"},
    },
)
def approve_product(product_id: uuid.UUID, operator: Operator, session: Db) -> ApproveProductOut:
    """A proposed product is active. An active one is left as it is."""
    status, changed = matching_service.operator_approve_product(session, product_id, operator)
    session.commit()
    return ApproveProductOut(product_id=product_id, status=status, changed=changed)


@router.post(
    "/products/merge",
    responses={
        404: {"description": "product_not_found"},
        409: {"description": "product_merged"},
        422: {"description": "invalid_merge: keep_id equals remove_id"},
    },
)
def merge(body: MergeIn, operator: Operator, session: Db) -> MergeOut:
    """Merge the duplicate remove_id into keep_id: its matches, observations and promotions move
    to keep_id, and it is merged_into keep_id. One transaction."""
    outcome = matching_service.merge_products(session, body.keep_id, body.remove_id, operator)
    session.commit()
    return MergeOut(
        keep_id=outcome.keep_id,
        remove_id=outcome.remove_id,
        remove_status="merged_into",
        aliases_moved=outcome.aliases_moved,
        barcode_moved=outcome.barcode_moved,
        observations_moved=outcome.observations_moved,
        promotion_products_moved=outcome.promotion_products_moved,
        votes_moved=outcome.votes_moved,
        candidates_removed=outcome.candidates_removed,
    )
