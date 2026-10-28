"""quota: HTTP routes. Calls service only, never repository."""

from fastapi import APIRouter

router = APIRouter(prefix="/quota", tags=["quota"])
