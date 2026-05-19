"""Views for the ``/admin/ingest`` endpoint group.

``trigger`` enqueues ``quake.tasks.poll_usgs`` on the Celery worker
queue and returns the new task id immediately — the actual ingestion
runs out-of-band. ``status`` reads the most recent ``ingestion_runs``
rows so operators can see the outcome of recent runs (both the
Beat-driven ones and the manual triggers).

Dispatch goes through ``celery_app.send_task(name)`` rather than the
typed ``poll_usgs.delay()`` because pyright sees the decorated task
as a plain ``FunctionType`` and doesn't know about Celery's runtime
``.delay`` attribute. ``send_task`` returns a properly-typed
``AsyncResult`` and is the canonical dispatch-by-name path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import Query

from config import celery_app
from database.etls.ingestion_runs import IngestionRunsETL
from quake.api.ingest.models import IngestRunResponse, IngestStatusResponse, TriggerResponse

_POLL_TASK_NAME = "quake.tasks.poll_usgs"


class IngestManagerViews:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def trigger(self) -> TriggerResponse:
        result = celery_app.send_task(_POLL_TASK_NAME)
        queued_at = datetime.now(timezone.utc)
        self.logger.info(
            "poll_usgs manually triggered",
            extra={"task_id": str(result.id), "queued_at": queued_at.isoformat()},
        )
        return TriggerResponse(task_id=str(result.id), queued_at=queued_at)

    async def status(self, limit: int = Query(default=10, ge=1, le=200)) -> IngestStatusResponse:
        rows = IngestionRunsETL().latest(limit)
        return IngestStatusResponse(
            count=len(rows),
            runs=[IngestRunResponse.model_validate(r) for r in rows],
        )
