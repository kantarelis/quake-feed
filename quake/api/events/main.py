"""Manager for the events API module.

Owns the ``APIRouter`` mounted at ``/events`` and instantiates the
``EventsManagerViews`` holding the endpoint coroutines.

Every route on this router requires a valid API key. The dependency is
declared once at the router level (Epic 5 — Task 3) rather than
repeated per route; scope is left unset so any non-revoked key passes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from quake.api.auth import Authenticate
from quake.api.events.views import EventsManagerViews


class EventsManager:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger if logger else logging.getLogger("EventsManager")
        self.router = APIRouter(prefix="/events", dependencies=[Depends(Authenticate())])
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
        self.router.add_api_route(
            "",
            endpoint=self.views.query,
            methods=["GET"],
            summary="Query earthquakes",
            description=(
                "Filter earthquakes by any combination of near=lat,lon + "
                "radius_km, min_magnitude, since (timezone-aware), and limit. "
                "All filters are optional and combinable."
            ),
            operation_id="events_query",
            tags=["Events"],
        )
        return self.router
