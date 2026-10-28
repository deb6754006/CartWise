"""All module routers. main.py mounts each one under /v1."""

from fastapi import APIRouter

from app.modules.catalog.routes import router as catalog_router
from app.modules.geo.routes import router as geo_router
from app.modules.identity.routes import router as identity_router
from app.modules.ingestion.routes import router as ingestion_router
from app.modules.lists.routes import router as lists_router
from app.modules.matching.routes import router as matching_router
from app.modules.pricing.routes import router as pricing_router
from app.modules.quota.routes import router as quota_router
from app.modules.receipts.routes import router as receipts_router
from app.modules.spending.routes import router as spending_router
from app.modules.trust.routes import router as trust_router

ROUTERS: list[APIRouter] = [
    identity_router,
    lists_router,
    catalog_router,
    pricing_router,
    ingestion_router,
    receipts_router,
    matching_router,
    trust_router,
    quota_router,
    spending_router,
    geo_router,
]
