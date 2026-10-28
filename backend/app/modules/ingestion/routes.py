"""ingestion: HTTP routes. Calls service only, never repository."""

from fastapi import APIRouter

router = APIRouter(prefix="/ingestion", tags=["ingestion"])
