"""Views for the ``/alerts/filters`` + ``/alerts/stream`` endpoint groups.

CRUD on :table:`quake.alert_filters`, scoped per API key. Every view
takes ``current_key: ApiKeyRow = Depends(Authenticate())`` and passes
``current_key.id`` into the ETL — both the WHERE clauses in
``AlertFiltersETL.update`` / ``delete`` and the explicit lookup in
``get_by_id`` use that ``api_key_id`` as a cross-key defence.

The empty-filter rule is enforced in :class:`AlertFilter`'s
``model_validator`` (Task 1), so the views never see one.

The SSE endpoint (``AlertsStreamManagerViews.stream``) lives here too.
It opens a long-lived Server-Sent-Events connection backed by an
in-process :class:`SubscriberRegistry` slot — filters are snapshotted
at connect time, the registry pushes matched envelopes into the slot's
asyncio queue, and the generator forwards them to the wire. The
``finally`` block unsubscribes the slot regardless of how the
connection closes (client drop, server shutdown, exception).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from database.etls.alert_filters import AlertFiltersETL
from database.models import ApiKeyRow
from models.alerts import AlertEnvelope
from quake.alerts.registry import get_registry
from quake.api.alerts.models import AlertFilter, AlertFilterResponse, AlertFiltersListResponse
from quake.api.auth import Authenticate

_QUEUE_POLL_S = 1.0
_SSE_PING_S = 15
_SSE_SEND_TIMEOUT_S = 15.0


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


class AlertsStreamManagerViews:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def stream(
        self,
        request: Request,
        current_key: ApiKeyRow = Depends(Authenticate()),
    ) -> EventSourceResponse:
        """Open an SSE stream of events matching this key's filters.

        Filters are snapshotted at connect time — mid-stream filter
        edits via ``/alerts/filters`` take effect only after the client
        reconnects (PLAN.md design choice 6). An empty filter set is
        a 400 rather than a stream that can never deliver anything.
        """
        filters = AlertFiltersETL().for_api_key(current_key.id)
        if not filters:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="no filters configured — POST one to /alerts/filters first",
            )

        logger = self.logger

        async def event_generator() -> AsyncGenerator[dict[str, Any], None]:
            # Pairing subscribe + unsubscribe inside the generator ties the
            # registry slot to the generator's own lifecycle: the slot is
            # created on first iteration and torn down by the finally on
            # close — no leak if the generator is closed before any frames
            # have been yielded.
            registry = get_registry()
            subscriber = registry.subscribe(current_key.id, filters)
            logger.info(
                "SSE subscriber connected",
                extra={
                    "sub_id": subscriber.id,
                    "api_key_id": current_key.id,
                    "filter_count": len(filters),
                },
            )
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        envelope: AlertEnvelope = await asyncio.wait_for(subscriber.queue.get(), timeout=_QUEUE_POLL_S)
                    except asyncio.TimeoutError:
                        # No event in this tick; loop back to re-check
                        # disconnect. sse-starlette's ping keeps the
                        # connection warm in the meantime.
                        continue
                    yield {"event": "alert", "data": envelope.model_dump_json()}
            finally:
                registry.unsubscribe(subscriber.id)
                logger.info(
                    "SSE subscriber disconnected",
                    extra={"sub_id": subscriber.id, "api_key_id": current_key.id},
                )

        return EventSourceResponse(
            event_generator(),
            ping=_SSE_PING_S,
            send_timeout=_SSE_SEND_TIMEOUT_S,
        )
