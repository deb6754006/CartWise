"""matching: HTTP routes. Calls service only, never repository."""

from fastapi import APIRouter

# Also imported for its side effect: it registers matching's account deletion hook.
from app.modules.matching import service as service

router = APIRouter(prefix="/matching", tags=["matching"])
