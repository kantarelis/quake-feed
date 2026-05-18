"""Manager for the main API module.

Owns the ``APIRouter`` for default endpoints (currently ``/health``) and
instantiates the ``MainManagerViews`` that hold the endpoint coroutines.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from quake.api.main.views import MainManagerViews


class MainManager:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger if logger else logging.getLogger("MainManager")
        self.router = APIRouter()
        self.views = MainManagerViews(logger=self.logger)

    def run(self) -> APIRouter:
        self.router.add_api_route(
            "/health",
            endpoint=self.views.health,
            methods=["GET"],
            summary="Service health check",
            description="Liveness probe returning service identity and version.",
            operation_id="main_health",
            tags=["Main"],
        )
        self.router.add_api_route(
            "/metrics",
            endpoint=self.views.metrics,
            methods=["GET"],
            summary="Prometheus metrics",
            description="Prometheus text exposition for every metric on the default registry.",
            operation_id="main_metrics",
            tags=["Main"],
        )
        self.router.add_api_route(
            "/env",
            endpoint=self.views.env,
            methods=["GET"],
            summary="Running environment summary",
            description="Returns ENVIRONMENT, APPLICATION_NAME, and the running version.",
            operation_id="main_env",
            tags=["Main"],
        )
        return self.router
