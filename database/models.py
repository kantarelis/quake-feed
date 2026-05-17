"""Pydantic row models — one per ``quake.*`` table.

Row-shape only: each model mirrors the columns of its table exactly. No
domain logic, no derived fields, no validators. Higher-level domain models
(``Event``, ``AlertFilter``, …) live under ``models/`` and are added in
later epics.

NOT NULL columns are required; nullable columns default to ``None``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _RowBase(BaseModel):
    """Shared config for every row model.

    - ``extra="forbid"`` — instantiation with an unknown column name raises
      ``ValidationError`` rather than silently dropping the value.
    - ``from_attributes=True`` — ``Model.model_validate(obj)`` reads attributes
      off arbitrary objects, useful when callers pass psycopg row objects
      directly instead of dicts.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class EventRow(_RowBase):
    """One row of ``quake.events``."""

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
    inserted_at: datetime
    updated_at: datetime


class EventRevisionRow(_RowBase):
    """One row of ``quake.event_revisions``."""

    id: int
    event_id: str
    observed_at: datetime
    old_magnitude: float | None = None
    new_magnitude: float | None = None
    old_depth_km: float | None = None
    new_depth_km: float | None = None
    old_place: str | None = None
    new_place: str | None = None


class ApiKeyRow(_RowBase):
    """One row of ``quake.api_keys``.

    The raw API key never lives here — only ``key_hash``. Raw keys are
    stored in Vault and presented to clients exactly once at issue time.
    """

    id: int
    key_hash: str
    label: str | None = None
    scopes: list[str]
    created_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None


class AlertFilterRow(_RowBase):
    """One row of ``quake.alert_filters``.

    Both ``bbox_*`` and ``center_*``/``radius_km`` columns are nullable; the
    filter shape (bbox XOR center+radius) is enforced application-side, not
    by the table.
    """

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


class EndpointLockRow(_RowBase):
    """One row of ``quake.endpoint_locks``."""

    lock_name: str
    is_locked: bool
    locked_by: str | None = None
    locked_at: datetime | None = None
    reason: str | None = None


class IngestionRunRow(_RowBase):
    """One row of ``quake.ingestion_runs``."""

    id: int
    started_at: datetime
    finished_at: datetime | None = None
    inserted_count: int
    updated_count: int
    revision_count: int
    error: str | None = None
