"""Main API module — health, metrics, env, etc.

Imports :mod:`functions.celery_metrics` for its side effect: registering
the Celery task counters on the global Prometheus registry. The Celery
worker triggers the same registration transitively via the task module;
the API process needs an explicit hook because nothing else in the
request path references the metrics module. Without this, ``/metrics``
would expose only the empty default registry in the API process.
"""

from functions import celery_metrics
