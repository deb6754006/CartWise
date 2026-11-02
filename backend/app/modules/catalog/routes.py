"""catalog: HTTP routes. Calls service only, never repository."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import require_subject
from app.core.db import get_session
from app.modules.catalog import service
from app.modules.catalog.schemas import ChainOut, ClubOut

# No prefix: catalog owns top-level resources (/v1/chains, /v1/clubs).
router = APIRouter(tags=["catalog"])


@router.get("/chains", dependencies=[Depends(require_subject)])
def list_chains(session: Annotated[Session, Depends(get_session)]) -> list[ChainOut]:
    return [ChainOut(id=c.id, name=c.name) for c in service.list_chains(session)]


@router.get("/clubs", dependencies=[Depends(require_subject)])
def list_clubs(session: Annotated[Session, Depends(get_session)]) -> list[ClubOut]:
    return [
        ClubOut(id=c.id, name=c.name, chain_id=c.chain_id, chain_name=c.chain_name)
        for c in service.list_clubs(session)
    ]
