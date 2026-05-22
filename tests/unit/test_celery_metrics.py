"""Unit tests for the worker metrics-exposition bootstrap.

These pin the Task-1 contract: a ``worker_init``-connected handler that starts
``prometheus_client.start_http_server`` on the configured port. ``start_http_server``
is always mocked — the test must never bind a real socket.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from celery.signals import worker_init

import functions.celery_metrics as celery_metrics
from functions.environment import get_environmental_variables


def test_handler_starts_http_server_on_configured_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """The handler binds the worker's configured metrics port (no real socket)."""
    fake_server = MagicMock()
    monkeypatch.setattr(celery_metrics, "start_http_server", fake_server)

    celery_metrics._start_metrics_server()

    expected_port = get_environmental_variables().worker.metrics_port
    fake_server.assert_called_once_with(expected_port)


def test_handler_is_connected_to_worker_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """Emitting ``worker_init`` runs the handler — proving the signal wiring."""
    fake_server = MagicMock()
    monkeypatch.setattr(celery_metrics, "start_http_server", fake_server)

    # send_robust isolates us from any unrelated receiver raising on the signal.
    worker_init.send_robust(sender=None)

    expected_port = get_environmental_variables().worker.metrics_port
    fake_server.assert_called_once_with(expected_port)
