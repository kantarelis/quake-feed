"""Unit tests for the main API module (health, metrics, env, ...).

Drives the assembled ``Quake.app`` through a ``TestClient`` so each
endpoint is exercised through the full FastAPI stack the same way
production clients hit it.

Every endpoint here is **intentionally public** (no API key required)
so ops + Prometheus can hit them unauthenticated. The fixture sets no
``Authorization`` header on purpose; if a future change accidentally
puts these routes behind :class:`quake.api.auth.Authenticate`, the
existing 200 assertions flip to 401 and this file fails loudly.
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


def test_env_returns_current_environment(client: TestClient) -> None:
    """`/env` echoes ENVIRONMENT + APPLICATION_NAME + running version.

    The sandbox conftest pins ``ENVIRONMENT=testing`` for the whole
    pytest session, so the response should reflect that.
    """
    response = client.get("/env")
    assert response.status_code == 200

    body = response.json()
    assert set(body.keys()) == {"environment", "application_name", "version"}
    assert body["environment"] == "testing"
    assert body["application_name"]
    assert body["version"]
