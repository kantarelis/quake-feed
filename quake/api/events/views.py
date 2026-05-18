"""Views for the events API module.

Endpoint coroutines live here; the :class:`EventsManager` in
``main.py`` owns the router and wires routes to these methods.
"""

from __future__ import annotations

import logging

from fastapi import Depends

from database.etls.events import EventsETL
from quake.api.events.models import EventResponse, EventsListResponse, RecentEventsQuery


class EventsManagerViews:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def recent(self, query: RecentEventsQuery = Depends()) -> EventsListResponse:
        rows = EventsETL().recent(query.limit)
        return EventsListResponse(
            count=len(rows),
            events=[EventResponse.model_validate(r) for r in rows],
        )
