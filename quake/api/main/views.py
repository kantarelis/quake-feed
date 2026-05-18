"""Views for the main API module (health/status endpoints)."""

from __future__ import annotations

import logging

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from __metadata__ import __title__, __version__
from functions.environment import get_environmental_variables
from quake.api.main.models import EnvResponse, HealthResponse


class MainManagerViews:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def health(self) -> HealthResponse:
        return HealthResponse(status="ok", service=__title__, version=__version__)

    async def metrics(self) -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    async def env(self) -> EnvResponse:
        env = get_environmental_variables()
        return EnvResponse(
            environment=env.environment.value,
            application_name=env.application_name,
            version=__version__,
        )
