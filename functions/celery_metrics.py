"""Prometheus instrumentation for Celery task lifecycle.

Importing this module registers signal handlers on the global Celery
dispatcher. The metrics surface is intentionally small at this stage; Epic 8
(observability) extends it with per-task latency buckets and richer labels.
"""

from __future__ import annotations

import time
from typing import Any

from celery.signals import task_failure, task_postrun, task_prerun
from prometheus_client import Counter, Histogram

CELERY_TASK_TOTAL = Counter(
    "celery_task_total",
    "Total number of Celery tasks executed, partitioned by name and outcome.",
    ["task_name", "status"],
)

CELERY_TASK_DURATION_SECONDS = Histogram(
    "celery_task_duration_seconds",
    "Celery task execution time in seconds.",
    ["task_name"],
)

# Per-task start timestamps, keyed by task_id. Cleaned up in task_postrun.
_task_starts: dict[str, float] = {}


@task_prerun.connect
def _on_task_prerun(task_id: str = "", task: Any = None, **_: Any) -> None:
    _task_starts[task_id] = time.monotonic()


@task_postrun.connect
def _on_task_postrun(task_id: str = "", task: Any = None, state: str = "", **_: Any) -> None:
    name = getattr(task, "name", "unknown")
    start = _task_starts.pop(task_id, None)
    if start is not None:
        CELERY_TASK_DURATION_SECONDS.labels(task_name=name).observe(time.monotonic() - start)
    CELERY_TASK_TOTAL.labels(task_name=name, status=(state or "UNKNOWN").lower()).inc()


@task_failure.connect
def _on_task_failure(task_id: str = "", sender: Any = None, **_: Any) -> None:
    # task_postrun fires after task_failure with state="FAILURE", so the counter
    # increment happens there. This handler is kept as a future hook point for
    # alerting / structured error enrichment (Epic 8).
    return None
