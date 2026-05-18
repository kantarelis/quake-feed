"""Request/response Pydantic models for the events API.

Public DTO shape lives here; the database-row shape stays in
``database.models``. The DTO drops internal timestamps (``inserted_at``,
``updated_at``) so they aren't part of the public API contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_LIMIT_DEFAULT = 100
_LIMIT_MIN = 1
_LIMIT_MAX = 1000


class EventResponse(BaseModel):
    """Public-API representation of one ``quake.events`` row.

    ``from_attributes=True`` lets ``EventResponse.model_validate(row)``
    consume a :class:`database.models.EventRow` directly.
    """

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    time: datetime
    magnitude: float
    magnitude_type: str | None = None
    depth_km: float | None = None
    latitude: float
    longitude: float
    place: str | None = None
    status: str | None = None
    tsunami: bool
    url: str | None = None


class EventsListResponse(BaseModel):
    """Envelope wrapping a list of events plus its size.

    The envelope (rather than a bare list) leaves room for future
    additions — paging cursors, totals, query echo — without breaking
    existing clients.
    """

    count: int
    events: list[EventResponse]


class RecentEventsQuery(BaseModel):
    """Query parameters for ``GET /events/recent``."""

    limit: int = Field(default=_LIMIT_DEFAULT, ge=_LIMIT_MIN, le=_LIMIT_MAX)


class EventsQuery(BaseModel):
    """Query parameters for the combined-filter ``GET /events`` endpoint.

    Every filter is optional and combinable. ``near`` and ``radius_km``
    must be supplied together — partial geographic input is a 422.
    """

    near: str | None = None
    radius_km: float | None = Field(default=None, gt=0.0, le=20_000.0)
    min_magnitude: float | None = Field(default=None, ge=-1.0, le=10.0)
    since: datetime | None = None
    limit: int = Field(default=_LIMIT_DEFAULT, ge=_LIMIT_MIN, le=_LIMIT_MAX)

    @field_validator("near")
    @classmethod
    def _validate_near(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split(",")
        if len(parts) != 2:
            raise ValueError("near must be formatted as 'lat,lon'")
        try:
            lat = float(parts[0])
            lon = float(parts[1])
        except ValueError as exc:
            raise ValueError("near must be 'lat,lon' with numeric components") from exc
        if not -90.0 <= lat <= 90.0:
            raise ValueError("near latitude must be in [-90, 90]")
        if not -180.0 <= lon <= 180.0:
            raise ValueError("near longitude must be in [-180, 180]")
        return value

    @field_validator("since")
    @classmethod
    def _validate_since_tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("since must be timezone-aware (e.g. '...Z' or '...+00:00')")
        return value

    @model_validator(mode="after")
    def _validate_near_radius_pair(self) -> Self:
        if (self.near is None) != (self.radius_km is None):
            raise ValueError("near and radius_km must be provided together")
        return self

    @property
    def parsed_near(self) -> tuple[float, float] | None:
        """Return ``(lat, lon)`` if ``near`` was supplied, else ``None``."""
        if self.near is None:
            return None
        lat_str, lon_str = self.near.split(",")
        return float(lat_str), float(lon_str)
