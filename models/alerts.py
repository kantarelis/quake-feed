"""Domain models for the alerts surface.

* :class:`AlertFilter` — request DTO for ``POST /alerts/filters`` and
  ``PATCH /alerts/filters/{id}``. Enforces the bbox-XOR-center+radius
  shape application-side so the DB stays free of the constraint.
* :class:`AlertFilterResponse` — public representation of one
  ``quake.alert_filters`` row. ``from_attributes=True`` so it consumes
  :class:`database.models.AlertFilterRow` directly.
* :class:`AlertEnvelope` — the SSE payload pushed to subscribers. Slim
  projection of :class:`database.models.EventRow`; internal timestamps
  (``inserted_at`` / ``updated_at``) and revision-only columns are
  intentionally omitted from the wire shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

_BBOX_FIELDS = ("bbox_min_lat", "bbox_min_lon", "bbox_max_lat", "bbox_max_lon")
_CENTER_FIELDS = ("center_lat", "center_lon", "radius_km")


class AlertFilter(BaseModel):
    """One filter row, as the client supplies it.

    The shape is *bbox XOR center+radius*, optionally combined with a
    ``min_magnitude`` floor. At least one predicate must be set —
    an entirely empty filter would match every event and is rejected
    so the operator can't accidentally fan out the firehose to a key.
    """

    model_config = ConfigDict(extra="forbid")

    min_magnitude: float | None = Field(default=None, ge=-1.0, le=10.0)

    bbox_min_lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    bbox_min_lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    bbox_max_lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    bbox_max_lon: float | None = Field(default=None, ge=-180.0, le=180.0)

    center_lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    center_lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    radius_km: float | None = Field(default=None, gt=0.0, le=20_000.0)

    @model_validator(mode="after")
    def _validate_shape(self) -> Self:
        bbox_values = [getattr(self, f) for f in _BBOX_FIELDS]
        center_values = [getattr(self, f) for f in _CENTER_FIELDS]
        bbox_set = sum(v is not None for v in bbox_values)
        center_set = sum(v is not None for v in center_values)

        if 0 < bbox_set < len(_BBOX_FIELDS):
            raise ValueError("bbox requires all of bbox_min_lat / bbox_min_lon / bbox_max_lat / bbox_max_lon")
        if 0 < center_set < len(_CENTER_FIELDS):
            raise ValueError("center+radius requires all of center_lat / center_lon / radius_km")
        if bbox_set and center_set:
            raise ValueError("bbox and center+radius are mutually exclusive — pick one shape")

        if self.min_magnitude is None and not bbox_set and not center_set:
            raise ValueError("empty filter — at least one of min_magnitude / bbox / center+radius must be set")

        # Bbox ordering check: ``bbox_set == len(_BBOX_FIELDS)`` means all four
        # values are non-None (the partial-set branch above raised already).
        if bbox_set == len(_BBOX_FIELDS):
            min_lat, min_lon, max_lat, max_lon = bbox_values
            if min_lat is not None and max_lat is not None and min_lat > max_lat:
                raise ValueError("bbox_min_lat must be <= bbox_max_lat")
            if min_lon is not None and max_lon is not None and min_lon > max_lon:
                raise ValueError("bbox_min_lon must be <= bbox_max_lon")

        return self


class AlertFilterResponse(BaseModel):
    """Public representation of one ``quake.alert_filters`` row."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    api_key_id: int
    min_magnitude: float | None = None
    bbox_min_lat: float | None = None
    bbox_min_lon: float | None = None
    bbox_max_lat: float | None = None
    bbox_max_lon: float | None = None
    center_lat: float | None = None
    center_lon: float | None = None
    radius_km: float | None = None
    created_at: datetime
    updated_at: datetime


class AlertEnvelope(BaseModel):
    """SSE payload pushed to subscribers on a new event.

    Slim projection of :class:`database.models.EventRow` —
    ``from_attributes=True`` lets the listener pass an ``EventRow``
    (or a row-shaped dict from the ``pg_notify`` payload) straight in.
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
    url: str | None = None
