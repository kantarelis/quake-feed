"""Manager for the events API module.

Owns the ``APIRouter`` mounted at ``/events`` and instantiates the
``EventsManagerViews`` holding the endpoint coroutines.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from quake.api.events.views import EventsManagerViews


class EventsManager:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger if logger else logging.getLogger("EventsManager")
        self.router = APIRouter(prefix="/events")
        self.views = EventsManagerViews(logger=self.logger)

    def run(self) -> APIRouter:
        self.router.add_api_route(
            "/recent",
            endpoint=self.views.recent,
            methods=["GET"],
            summary="Recent earthquakes",
            description="Last N events, newest first.",
            operation_id="events_recent",
            tags=["Events"],
        )
        return self.router
