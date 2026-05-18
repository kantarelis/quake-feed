"""Views for the main API module (health/status endpoints)."""

from __future__ import annotations

import logging

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from __metadata__ import __title__, __version__
from quake.api.main.models import HealthResponse


class MainManagerViews:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def health(self) -> HealthResponse:
        return HealthResponse(status="ok", service=__title__, version=__version__)

    async def metrics(self) -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
