"""Top-level FastAPI application factory.

The ``Quake`` class assembles the application: constructs every Manager,
mounts its router on the FastAPI app, and exposes ``run()`` to start the
Uvicorn server. New API modules added in later epics are wired in here.
"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from __metadata__ import __description__, __title__, __version__
from quake.api.events.main import EventsManager
from quake.api.main.main import MainManager


class Quake:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.app = FastAPI(
            title=__title__,
            description=__description__,
            version=__version__,
        )
        self._mount_routers()

    def _mount_routers(self) -> None:
        main_manager = MainManager(logger=self.logger)
        self.app.include_router(main_manager.run())
        events_manager = EventsManager(logger=self.logger)
        self.app.include_router(events_manager.run())

    def run(self, host: str, port: int) -> None:
        self.logger.info("Starting quake-feed", extra={"host": host, "port": port})
        uvicorn.run(self.app, host=host, port=port)
