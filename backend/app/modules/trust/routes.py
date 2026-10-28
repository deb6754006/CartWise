"""trust: HTTP routes. Calls service only, never repository."""

from fastapi import APIRouter

router = APIRouter(prefix="/trust", tags=["trust"])
