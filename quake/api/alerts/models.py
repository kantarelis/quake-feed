"""Response envelopes for the ``/alerts/filters`` endpoint group.

The request DTO (:class:`AlertFilter`) and the row response shape
(:class:`AlertFilterResponse`) live in ``models/alerts.py`` (Task 1)
and are re-exported from this module so the OpenAPI schema cohesion
across the alerts API mirrors how callers actually import them.
"""

from __future__ import annotations

from pydantic import BaseModel

from models.alerts import AlertFilter, AlertFilterResponse

__all__ = ["AlertFilter", "AlertFilterResponse", "AlertFiltersListResponse"]


class AlertFiltersListResponse(BaseModel):
    """Envelope wrapping the caller's filters plus the row count.

    The envelope (rather than a bare list) leaves room for future
    additions — paging cursors, totals, query echo — without breaking
    existing clients. Mirrors :class:`quake.api.events.models.EventsListResponse`.
    """

    count: int
    filters: list[AlertFilterResponse]
