"""Views for the main API module (health/status endpoints)."""

from __future__ import annotations

import logging

from __metadata__ import __title__, __version__
from quake.api.main.models import HealthResponse


class MainManagerViews:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def health(self) -> HealthResponse:
        return HealthResponse(status="ok", service=__title__, version=__version__)
