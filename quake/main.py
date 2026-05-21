"""Top-level FastAPI application factory.

The ``Quake`` class assembles the application: constructs every Manager,
mounts its router on the FastAPI app, and exposes ``run()`` to start the
Uvicorn server. New API modules added in later epics are wired in here.

The app's lifespan owns the :class:`AlertListener` background task —
started on app boot, cancelled cleanly on shutdown. Test fixtures that
construct ``TestClient(quake.app)`` without entering its context manager
do not trigger the lifespan (starlette behaviour), so they don't start
a live listener; tests that need one (Task 8 integration smoke) use
``with TestClient(quake.app) as client:`` to opt in.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, status
from fastapi.responses import FileResponse, Response

from __metadata__ import __description__, __title__, __version__
from quake.alerts.listener import AlertListener
from quake.alerts.registry import get_registry
from quake.api.alerts.main import AlertFiltersManager, AlertsStreamManager
from quake.api.events.main import EventsManager
from quake.api.ingest.main import IngestManager
from quake.api.locks.main import LocksManager
from quake.api.main.main import MainManager

# The Vite build lands in <repo-root>/frontend/dist; the multi-stage Dockerfile
# copies it to the same path inside the image. quake/main.py → quake/ → root.
_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _frontend_dist() -> Path | None:
    """Return the resolved SPA build dir if it holds an index.html, else None."""
    dist = _DIST_DIR.resolve()
    if (dist / "index.html").is_file():
        return dist
    return None


class Quake:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.app = FastAPI(
            title=__title__,
            description=__description__,
            version=__version__,
            lifespan=self._lifespan,
        )
        self._spa_dist: Path | None = None
        self._mount_routers()
        self._mount_spa()

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        """Start the AlertListener on boot, cancel it cleanly on shutdown."""
        listener = AlertListener(registry=get_registry())
        task = asyncio.create_task(listener.run(), name="alert-listener")
        self.logger.info("AlertListener started")
        try:
            yield
        finally:
            listener.stop()
            try:
                await asyncio.wait_for(task, timeout=10.0)
            except asyncio.TimeoutError:
                self.logger.warning("AlertListener did not stop within 10s — cancelling")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self.logger.info("AlertListener stopped")

    def _mount_routers(self) -> None:
        main_manager = MainManager(logger=self.logger)
        self.app.include_router(main_manager.run())
        events_manager = EventsManager(logger=self.logger)
        self.app.include_router(events_manager.run())
        locks_manager = LocksManager(logger=self.logger)
        self.app.include_router(locks_manager.run())
        ingest_manager = IngestManager(logger=self.logger)
        self.app.include_router(ingest_manager.run())
        alert_filters_manager = AlertFiltersManager(logger=self.logger)
        self.app.include_router(alert_filters_manager.run())
        alerts_stream_manager = AlertsStreamManager(logger=self.logger)
        self.app.include_router(alerts_stream_manager.run())

    def _mount_spa(self) -> None:
        """Serve the built SPA at ``/`` with an index.html fallback.

        Registered *after* every API router, so the catch-all only handles
        paths no router (and none of FastAPI's ``/docs`` / ``/openapi.json``
        routes) claimed — nothing is shadowed. No-ops when the build is
        absent (a dev backend running without ``make frontend-build``).
        """
        dist = _frontend_dist()
        if dist is None:
            self.logger.info("frontend build not found; SPA serving disabled")
            return
        self._spa_dist = dist
        self.app.add_api_route(
            "/{full_path:path}",
            endpoint=self._serve_spa,
            methods=["GET"],
            include_in_schema=False,
        )

    async def _serve_spa(self, full_path: str) -> Response:
        """Return the requested static file, or index.html for SPA deep links.

        ``is_relative_to`` rejects ``..`` traversal so only files inside the
        build dir are served; anything else falls back to index.html and the
        client-side router resolves it.
        """
        dist = self._spa_dist
        if dist is None:  # defensive: route is only mounted when dist exists
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    def run(self, host: str, port: int) -> None:
        self.logger.info("Starting quake-feed", extra={"host": host, "port": port})
        uvicorn.run(self.app, host=host, port=port)
