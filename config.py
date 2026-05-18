"""Top-level Celery application.

Imported as ``from config import celery_app`` by worker and beat processes.
``include=["quake.tasks"]`` ensures the task module is loaded under
``celery -A config.celery_app worker`` so the ``@celery_app.task``
registrations actually take effect.
"""

from __future__ import annotations

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
