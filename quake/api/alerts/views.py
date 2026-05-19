"""Views for the ``/alerts/filters`` endpoint group.

CRUD on :table:`quake.alert_filters`, scoped per API key. Every view
takes ``current_key: ApiKeyRow = Depends(Authenticate())`` and passes
``current_key.id`` into the ETL — both the WHERE clauses in
``AlertFiltersETL.update`` / ``delete`` and the explicit lookup in
``get_by_id`` use that ``api_key_id`` as a cross-key defence.

The empty-filter rule is enforced in :class:`AlertFilter`'s
``model_validator`` (Task 1), so the views never see one.
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, status

from database.etls.alert_filters import AlertFiltersETL
from database.models import ApiKeyRow
from quake.api.alerts.models import AlertFilter, AlertFilterResponse, AlertFiltersListResponse
from quake.api.auth import Authenticate


class AlertFiltersManagerViews:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def list_filters(self, current_key: ApiKeyRow = Depends(Authenticate())) -> AlertFiltersListResponse:
        rows = AlertFiltersETL().for_api_key(current_key.id)
        return AlertFiltersListResponse(
            count=len(rows),
            filters=[AlertFilterResponse.model_validate(r) for r in rows],
        )

    async def create_filter(
        self,
        body: AlertFilter,
        current_key: ApiKeyRow = Depends(Authenticate()),
    ) -> AlertFilterResponse:
        filters = AlertFiltersETL()
        filter_id = filters.insert(api_key_id=current_key.id, **body.model_dump())
        row = filters.get_by_id(filter_id, current_key.id)
        # The row was just inserted and is_scoped to this key — None here
        # would be a DB-level surprise (race with a concurrent delete from
        # this same key). 500 is the right answer; the API client can retry.
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="filter inserted but not found on read-back",
            )
        return AlertFilterResponse.model_validate(row)

    async def update_filter(
        self,
        filter_id: int,
        body: AlertFilter,
        current_key: ApiKeyRow = Depends(Authenticate()),
    ) -> AlertFilterResponse:
        filters = AlertFiltersETL()
        ok = filters.update(filter_id, current_key.id, **body.model_dump())
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no such filter: {filter_id}",
            )
        row = filters.get_by_id(filter_id, current_key.id)
        if row is None:
            # Same race-with-delete reasoning as create — surface a 500.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="filter updated but not found on read-back",
            )
        return AlertFilterResponse.model_validate(row)

    async def delete_filter(
        self,
        filter_id: int,
        current_key: ApiKeyRow = Depends(Authenticate()),
    ) -> None:
        ok = AlertFiltersETL().delete(filter_id, current_key.id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no such filter: {filter_id}",
            )
        return None
