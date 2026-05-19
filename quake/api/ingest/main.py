"""Manager for the ``/admin/ingest`` endpoint group.

Admin scope (``Authenticate(required_scope="admin")``) is declared
at the router level so every route inherits it.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from quake.api.auth import Authenticate
from quake.api.ingest.views import IngestManagerViews


class IngestManager:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger if logger else logging.getLogger("IngestManager")
        self.router = APIRouter(
            prefix="/admin/ingest",
            dependencies=[Depends(Authenticate(required_scope="admin"))],
        )
        self.views = IngestManagerViews(logger=self.logger)

    def run(self) -> APIRouter:
        self.router.add_api_route(
            "/trigger",
            endpoint=self.views.trigger,
            methods=["POST"],
            summary="Trigger a poll_usgs run",
            description="Enqueues poll_usgs on Celery and returns the new task id. Run outcome surfaces in /status.",
            operation_id="admin_ingest_trigger",
            tags=["Admin"],
        )
        self.router.add_api_route(
            "/status",
            endpoint=self.views.status,
            methods=["GET"],
            summary="Recent ingestion runs",
            description="Return the most-recent ingestion_runs rows (newest first), capped by 'limit'.",
            operation_id="admin_ingest_status",
            tags=["Admin"],
        )
        return self.router
