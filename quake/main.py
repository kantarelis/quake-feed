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

import uvicorn
from fastapi import FastAPI

from __metadata__ import __description__, __title__, __version__
from quake.alerts.listener import AlertListener
from quake.alerts.registry import get_registry
from quake.api.events.main import EventsManager
from quake.api.ingest.main import IngestManager
from quake.api.locks.main import LocksManager
from quake.api.main.main import MainManager


class Quake:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.app = FastAPI(
            title=__title__,
            description=__description__,
            version=__version__,
            lifespan=self._lifespan,
        )
        self._mount_routers()

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

    def run(self, host: str, port: int) -> None:
        self.logger.info("Starting quake-feed", extra={"host": host, "port": port})
        uvicorn.run(self.app, host=host, port=port)
