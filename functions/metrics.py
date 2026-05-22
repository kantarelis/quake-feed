"""Application/domain Prometheus metrics.

Module-level metric objects live on the default registry; importing this module
is the only registration step (same pattern as :mod:`functions.celery_metrics`).

The ingestion counters/histogram below are incremented inside
:func:`quake.events.ingest.poll_once`, which runs in the Celery worker — so they
surface on the worker's ``:8001/metrics`` exporter (Task 1). The
``sse_connections_active`` gauge added later in this epic is incremented in the
API process and surfaces on the API's ``:8000/metrics`` instead.

Names match the Epic-8 catalogue. ``prometheus_client`` derives sample names by
convention: a ``Counter`` named ``events_inserted_total`` exposes the
``events_inserted_total`` sample; a ``Histogram`` named ``usgs_poll_seconds``
exposes ``usgs_poll_seconds_count`` / ``_sum`` / ``_bucket``.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

USGS_POLL_SECONDS = Histogram(
    "usgs_poll_seconds",
    "Duration of one USGS fetch/parse/upsert cycle, in seconds (observed on both success and failure).",
)

USGS_POLL_ERRORS_TOTAL = Counter(
    "usgs_poll_errors_total",
    "USGS poll cycles that raised before completing.",
)

EVENTS_INSERTED_TOTAL = Counter(
    "events_inserted_total",
    "Earthquake events inserted, summed across all poll cycles.",
)

EVENTS_UPDATED_TOTAL = Counter(
    "events_updated_total",
    "Earthquake events updated, summed across all poll cycles.",
)

EVENTS_REVISIONS_TOTAL = Counter(
    "events_revisions_total",
    "Event revisions written by the DB trigger, summed across all poll cycles.",
)
