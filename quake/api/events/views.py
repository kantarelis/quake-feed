"""Views for the events API module.

Endpoint coroutines live here; the :class:`EventsManager` in
``main.py`` owns the router and wires routes to these methods.

Query-parameter models are bound via ``Annotated[Model, Query()]``
rather than ``Depends()`` so that ``@field_validator`` /
``@model_validator`` failures propagate through FastAPI's request-
validation pipeline as 422 responses (the ``Depends(Model)`` path
leaks them as unhandled 500s).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Query

from database.etls.events import EventsETL
from quake.api.events.models import (
    EventResponse,
    EventsListResponse,
    EventsQuery,
    RecentEventsQuery,
)


class EventsManagerViews:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def recent(self, query: Annotated[RecentEventsQuery, Query()]) -> EventsListResponse:
        rows = EventsETL().recent(query.limit)
        return EventsListResponse(
            count=len(rows),
            events=[EventResponse.model_validate(r) for r in rows],
        )

    async def query(self, query: Annotated[EventsQuery, Query()]) -> EventsListResponse:
        rows = EventsETL().query(
            near=query.parsed_near,
            radius_km=query.radius_km,
            min_magnitude=query.min_magnitude,
            since=query.since,
            limit=query.limit,
        )
        return EventsListResponse(
            count=len(rows),
            events=[EventResponse.model_validate(r) for r in rows],
        )
