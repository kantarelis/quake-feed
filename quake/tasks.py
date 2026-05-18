"""Celery task registry.

Imported by :mod:`config` via ``include=["quake.tasks"]`` so the
``@celery_app.task`` decorators register on worker boot. The Beat
schedule in :mod:`config` references these tasks by name.

* ``poll_usgs`` — Beat-driven 60-second wrapper around
  :func:`quake.events.ingest.poll_once`. ``max_retries=0`` because
  retry/backoff already lives inside :class:`UsgsClient`; a Celery-level
  retry would double-retry and double-record the run.
* ``health_check`` — DB liveness probe (``SELECT 1``) for the
  observability stack to call on demand.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from celery import Task

from config import celery_app
from database.main import transaction
from functions.logger import setup_logger
from quake.events.ingest import poll_once

logger = setup_logger("tasks", "quake-feed")


@celery_app.task(name="quake.tasks.poll_usgs", bind=True, max_retries=0)
def poll_usgs(self: Task) -> dict[str, Any]:
    """Run one USGS poll cycle and return the result dict."""
    result = poll_once()
    return result.model_dump()


@celery_app.task(name="quake.tasks.health_check")
def health_check() -> dict[str, str]:
    """Ping the DB with ``SELECT 1`` and return a liveness envelope."""
    with transaction() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}
