"""Unit tests for the main API module (health, metrics, env, ...).

Drives the assembled ``Quake.app`` through a ``TestClient`` so each
endpoint is exercised through the full FastAPI stack the same way
production clients hit it.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from quake.main import Quake


@pytest.fixture
def client() -> TestClient:
    quake = Quake(logger=logging.getLogger("test-main-api"))
    return TestClient(quake.app)


def test_metrics_returns_prometheus_exposition(client: TestClient) -> None:
    """`/metrics` returns Prometheus text exposition including the celery counter.

    ``celery_task_total`` is defined by ``functions.celery_metrics`` and
    is loaded into the default registry by ``quake.api.main.__init__``;
    even before any Celery task fires, its HELP/TYPE header lines appear
    in the exposition output.
    """
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "celery_task_total" in response.text
