"""geo: HTTP routes. Calls service only, never repository."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import StringConstraints

from app.core.auth import Subject, require_subject
from app.modules.geo import service
from app.modules.geo.schemas import ADDRESS_MAX_LENGTH, ADDRESS_MIN_LENGTH, GeocodeOut

router = APIRouter(prefix="/geo", tags=["geo"])

Address = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=ADDRESS_MIN_LENGTH, max_length=ADDRESS_MAX_LENGTH
    ),
    Query(),
]


@router.get(
    "/geocode",
    responses={
        404: {"description": "address_not_found"},
        503: {"description": "geocoding_unavailable"},
    },
)
def geocode(
    q: Address,
    _subject: Annotated[Subject, Depends(require_subject)],
    geocoder: Annotated[service.Geocoder, Depends(service.get_geocoder)],
) -> GeocodeOut:
    """The coordinates of an address in Israel. The address is not kept or logged."""
    point = service.locate_address(geocoder, q)
    return GeocodeOut(lat=point.lat, lng=point.lng)
