"""Request/response models for the ``/admin/ingest`` endpoint group."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TriggerResponse(BaseModel):
    """Reply from ``POST /admin/ingest/trigger``.

    The task runs out-of-band on a Celery worker; this response only
    confirms enqueue. ``GET /admin/ingest/status`` is where the actual
    outcome shows up.
    """

    task_id: str
    queued_at: datetime


class IngestRunResponse(BaseModel):
    """Public representation of one ``quake.ingestion_runs`` row."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None = None
    inserted_count: int
    updated_count: int
    revision_count: int
    error: str | None = None


class IngestStatusResponse(BaseModel):
    """Envelope wrapping the most-recent ingestion runs + their count."""

    count: int
    runs: list[IngestRunResponse]
