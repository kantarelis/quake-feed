"""End-to-end smoke for the Celery ``poll_usgs`` task.

Self-contained: ``tests/integration/conftest.py`` brings up a fresh
TimescaleDB on host port 5436, applies migrations, runs, and tears down.
The full ``docker-compose`` stack is **not** required — only Docker (for
the DB) and outbound HTTPS (for real USGS).

Operator workflow:

    make test-integration   # spins up DB, hits real USGS, asserts, cleans up

The test is intentionally tolerant of two real-world conditions:

* **USGS occasionally returns 0 events** in a quiet hour. A clean run
  with zero inserts is still a passing end-to-end signal — the assertion
  is "did the pipeline complete without error", not "did we observe
  seismic activity".
* **Re-runs** see the second call's UPSERTs resolve as updates (not
  inserts) because the conftest only truncates at session start. We
  assert on internal consistency (``run.inserted_count == payload['inserted']``)
  rather than absolute counts.
"""

from __future__ import annotations

import importlib

import pytest

from config import celery_app
from database.etls.events import EventsETL
from database.etls.ingestion_runs import IngestionRunsETL

importlib.import_module("quake.tasks")

pytestmark = pytest.mark.integration

_POLL_NAME = "quake.tasks.poll_usgs"


def test_poll_usgs_completes_against_live_stack() -> None:
    payload = celery_app.tasks[_POLL_NAME].apply().get()

    # The task body returned cleanly (no exception captured into the dict).
    assert payload["error"] is None
    assert payload["inserted"] >= 0
    assert payload["updated"] >= 0
    assert payload["revisions"] >= 0

    # The ingestion_runs row was finalized.
    latest = IngestionRunsETL().latest(1)
    assert len(latest) == 1
    run = latest[0]
    assert run.finished_at is not None
    assert run.error is None
    assert run.inserted_count == payload["inserted"]
    assert run.updated_count == payload["updated"]
    assert run.revision_count == payload["revisions"]

    # If anything was inserted or already existed, quake.events has rows.
    # Skip this read-back when both counts are 0 (USGS returned an empty hour
    # and the table happens to be empty — rare, but possible on a fresh DB).
    if payload["inserted"] + payload["updated"] > 0:
        recent = EventsETL().recent(1)
        assert len(recent) == 1
