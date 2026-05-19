"""Manager for the ``/alerts/filters`` endpoint group.

Per-API-key CRUD on persistent alert filters. Auth is declared at the
view-signature level (not the router level) because each view needs
the resolved :class:`ApiKeyRow` to scope its ETL calls; a single
view-level ``Depends(Authenticate())`` per route is enough — see
``views.py`` for the rationale.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status

from quake.api.alerts.views import AlertFiltersManagerViews


class AlertFiltersManager:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger if logger else logging.getLogger("AlertFiltersManager")
        self.router = APIRouter(prefix="/alerts/filters")
        self.views = AlertFiltersManagerViews(logger=self.logger)

    def run(self) -> APIRouter:
        self.router.add_api_route(
            "",
            endpoint=self.views.list_filters,
            methods=["GET"],
            summary="List this key's alert filters",
            description="Return every quake.alert_filters row owned by the authenticated key.",
            operation_id="alerts_filters_list",
            tags=["Alerts"],
        )
        self.router.add_api_route(
            "",
            endpoint=self.views.create_filter,
            methods=["POST"],
            summary="Create a new alert filter",
            description=(
                "Persist a filter scoped to the authenticated key. Body validates as AlertFilter — "
                "bbox XOR center+radius, optionally combined with min_magnitude. An empty filter "
                "(no predicates) is rejected with 422."
            ),
            operation_id="alerts_filters_create",
            status_code=status.HTTP_201_CREATED,
            tags=["Alerts"],
        )
        self.router.add_api_route(
            "/{filter_id}",
            endpoint=self.views.update_filter,
            methods=["PATCH"],
            summary="Replace one alert filter",
            description=(
                "Full-replacement update of one filter's fields. The filter must belong to the "
                "authenticated key; unknown ids and cross-key ids both return 404."
            ),
            operation_id="alerts_filters_update",
            tags=["Alerts"],
        )
        self.router.add_api_route(
            "/{filter_id}",
            endpoint=self.views.delete_filter,
            methods=["DELETE"],
            summary="Delete one alert filter",
            description="Remove a filter owned by the authenticated key. Unknown ids return 404.",
            operation_id="alerts_filters_delete",
            status_code=status.HTTP_204_NO_CONTENT,
            tags=["Alerts"],
        )
        return self.router
