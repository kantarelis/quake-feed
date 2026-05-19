"""Request/response models for the ``/admin/locks`` endpoint group."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LockResponse(BaseModel):
    """Public representation of one ``quake.endpoint_locks`` row."""

    model_config = ConfigDict(from_attributes=True)

    lock_name: str
    is_locked: bool
    locked_by: str | None = None
    locked_at: datetime | None = None
    reason: str | None = None


class LocksListResponse(BaseModel):
    """Envelope wrapping the locks list + its size."""

    count: int
    locks: list[LockResponse]


class SetLockRequest(BaseModel):
    """Body for ``POST /admin/locks/{lock_name}``.

    Both fields are optional metadata. The lock itself flips on via the
    POST regardless of what's in the body.
    """

    locked_by: str | None = None
    reason: str | None = None
