"""geo: Pydantic request/response schemas."""

from pydantic import BaseModel

ADDRESS_MIN_LENGTH = 2
ADDRESS_MAX_LENGTH = 200


class GeocodeOut(BaseModel):
    lat: float
    lng: float
