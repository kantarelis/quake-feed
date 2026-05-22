"""Top-level Celery application.

Imported as ``from config import celery_app`` by worker and beat processes.
``include=["quake.tasks"]`` ensures the task module is loaded under
``celery -A config.celery_app worker`` so the ``@celery_app.task``
registrations actually take effect.
"""

from __future__ import annotations

import importlib

from celery import Celery

from functions.environment import get_environmental_variables

_env = get_environmental_variables()
_rmq = _env.rabbitmq

BROKER_URL = f"amqp://{_rmq.username}:{_rmq.password}@{_rmq.host}:{_rmq.amqp_port}//"

celery_app = Celery(
    _env.application_name,
    broker=BROKER_URL,
    include=["quake.tasks"],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "poll_usgs_every_60s": {
            "task": "quake.tasks.poll_usgs",
            "schedule": 60.0,
        },
    },
)

# Side-effect import: registers the Celery signal instrumentation defined in
# functions.celery_metrics (per-task counters/latency + the worker_init hook
# that starts the worker's Prometheus HTTP exporter) whenever the Celery app is
# loaded — i.e. in the worker and beat processes. Routed through importlib so it
# reads as an intentional side effect rather than an unused import. The API
# process registers the same handlers via quake/api/main's own import.
importlib.import_module("functions.celery_metrics")
