"""Orchestrate one USGS poll cycle.

``poll_once`` is the single entry point: fetch the USGS feed, parse it,
upsert the batch through :class:`EventsETL`, count revisions written by
the DB trigger, and stamp the run in ``quake.ingestion_runs``. On
failure, the run row records the error string and the exception is
re-raised so callers (Celery, manual ops) see the failure too.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from database.etls.endpoint_locks import EndpointLocksETL
from database.etls.events import EventsETL
from database.etls.ingestion_runs import IngestionRunsETL
from database.etls.revisions import RevisionsETL
from functions.logger import setup_logger
from functions.metrics import (
    EVENTS_INSERTED_TOTAL,
    EVENTS_REVISIONS_TOTAL,
    EVENTS_UPDATED_TOTAL,
    USGS_POLL_ERRORS_TOTAL,
    USGS_POLL_SECONDS,
)
from quake.ingestion.usgs.client import UsgsClient, UsgsFeed
from quake.ingestion.usgs.parser import parse_feed

logger = setup_logger("ingest", "quake-feed")

_INGESTION_LOCK = "INGESTION_LOCK"
_LOCK_SKIP_REASON = f"{_INGESTION_LOCK} active"


class IngestionResult(BaseModel):
    """Typed return value from :func:`poll_once`."""

    inserted: int
    updated: int
    revisions: int
    error: str | None = None


def poll_once(
    client: UsgsClient | None = None,
    feed: UsgsFeed = UsgsFeed.ALL_HOUR,
) -> IngestionResult:
    """Run one fetch → parse → upsert → record-run cycle.

    Passing ``client`` is how tests inject a mock; in production the
    function owns the client lifecycle (created here, closed in a
    ``finally`` block).

    The ``run_started`` timestamp is captured *before* :meth:`start_run`
    so that the post-upsert ``RevisionsETL.count_since(run_started)`` query
    catches every revision the trigger writes during this cycle (revision
    rows have ``observed_at = now()`` set by the trigger itself, which
    runs strictly after ``run_started``).

    On any exception inside the fetch/parse/upsert block, the run row is
    finalised with ``error=str(exc)`` and the exception is re-raised
    unchanged so the caller's failure handling still sees it.
    """
    runs_etl = IngestionRunsETL()

    # Kill-switch gate (Epic 5 — Task 4). When the operator has set
    # INGESTION_LOCK via /admin/locks, record the skip and bail before
    # opening a UsgsClient or hitting USGS.
    if EndpointLocksETL().is_locked(_INGESTION_LOCK):
        run_id = runs_etl.record_skipped(_LOCK_SKIP_REASON)
        logger.info("poll_once skipped: lock active", extra={"run_id": run_id, "lock": _INGESTION_LOCK})
        return IngestionResult(inserted=0, updated=0, revisions=0, error=_LOCK_SKIP_REASON)

    run_started = datetime.now(timezone.utc)
    run_id = runs_etl.start_run()

    own_client = client is None
    client = client if client is not None else UsgsClient()
    try:
        try:
            # USGS_POLL_SECONDS.time() observes the elapsed time on block exit,
            # whether it completes or raises — so failed polls are timed too.
            with USGS_POLL_SECONDS.time():
                raw = client.fetch(feed)
                events = parse_feed(raw)
                counts = EventsETL().upsert_many(events)
                revisions = RevisionsETL().count_since(run_started)
        except Exception as exc:
            error = str(exc)
            USGS_POLL_ERRORS_TOTAL.inc()
            logger.exception("poll_once failed", extra={"run_id": run_id, "error": error})
            runs_etl.finish_run(run_id, inserted=0, updated=0, revisions=0, error=error)
            raise

        runs_etl.finish_run(
            run_id,
            inserted=counts["inserted"],
            updated=counts["updated"],
            revisions=revisions,
        )
        EVENTS_INSERTED_TOTAL.inc(counts["inserted"])
        EVENTS_UPDATED_TOTAL.inc(counts["updated"])
        EVENTS_REVISIONS_TOTAL.inc(revisions)
        result = IngestionResult(
            inserted=counts["inserted"],
            updated=counts["updated"],
            revisions=revisions,
        )
        logger.info("poll_once complete", extra={"run_id": run_id, **result.model_dump()})
        return result
    finally:
        if own_client:
            client.close()
