"""Unit tests for the ``/admin/ingest`` Manager + Views.

Mirrors the locks test layout: three fixture flavours (``admin_client``
/ ``read_client`` / ``no_auth_client``) all sharing a Vault override.
``celery_app.send_task`` is monkey-patched so the test never enqueues
a real Celery task — the trigger view just needs an object with an
``id``. (Patching ``send_task`` rather than ``poll_usgs.delay`` matches
the dispatch path actually used in ``quake/api/ingest/views.py``;
see the views module docstring for why ``send_task`` is preferred.)
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from database.etls.ingestion_runs import IngestionRunsETL
from quake.api.auth import get_vault_client
from quake.main import Quake
from tests._auth import StubVault, issue_test_key


def _build(name: str) -> tuple[TestClient, StubVault]:
    vault = StubVault()
    quake = Quake(logger=logging.getLogger(name))
    quake.app.dependency_overrides[get_vault_client] = lambda: vault
    return TestClient(quake.app), vault


@pytest.fixture
def admin_client() -> TestClient:
    client, vault = _build("test-ingest-api-admin")
    _, headers = issue_test_key(vault=vault, scopes=["admin"])
    client.headers.update(headers)
    return client


@pytest.fixture
def read_client() -> TestClient:
    client, vault = _build("test-ingest-api-read")
    _, headers = issue_test_key(vault=vault, scopes=[])
    client.headers.update(headers)
    return client


@pytest.fixture
def no_auth_client() -> TestClient:
    client, _ = _build("test-ingest-api-noauth")
    return client


class _StubAsyncResult:
    """Mimic the minimal surface trigger reads from a Celery AsyncResult."""

    def __init__(self, task_id: str) -> None:
        self.id = task_id


# ---------------------------------------------------------------------------
# trigger
# ---------------------------------------------------------------------------


def test_trigger_enqueues_task(admin_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Admin key + monkeypatched send_task → 200 with the stub's task_id echoed back."""
    calls: list[Any] = []

    def _fake_send_task(name: str) -> _StubAsyncResult:
        calls.append(name)
        return _StubAsyncResult("test-task-id-abc123")

    monkeypatch.setattr("quake.api.ingest.views.celery_app.send_task", _fake_send_task)

    response = admin_client.post("/admin/ingest/trigger")
    assert response.status_code == 200

    body = response.json()
    assert body["task_id"] == "test-task-id-abc123"
    assert "queued_at" in body and body["queued_at"]  # ISO-8601 string
    assert calls == ["quake.tasks.poll_usgs"]  # send_task invoked with the right name


def test_trigger_no_key_is_401(no_auth_client: TestClient) -> None:
    response = no_auth_client.post("/admin/ingest/trigger")
    assert response.status_code == 401


def test_trigger_non_admin_key_is_403(read_client: TestClient) -> None:
    response = read_client.post("/admin/ingest/trigger")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_returns_latest_runs(admin_client: TestClient) -> None:
    runs_etl = IngestionRunsETL()
    run1 = runs_etl.start_run()
    runs_etl.finish_run(run1, inserted=1, updated=0, revisions=0)
    run2 = runs_etl.start_run()
    runs_etl.finish_run(run2, inserted=2, updated=1, revisions=0)

    response = admin_client.get("/admin/ingest/status")
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 2
    # newest-first (started_at DESC, id DESC) — run2 outranks run1.
    assert [r["id"] for r in body["runs"]] == [run2, run1]
    assert body["runs"][0]["inserted_count"] == 2


def test_status_respects_limit(admin_client: TestClient) -> None:
    runs_etl = IngestionRunsETL()
    for _ in range(5):
        rid = runs_etl.start_run()
        runs_etl.finish_run(rid, inserted=0, updated=0, revisions=0)

    response = admin_client.get("/admin/ingest/status", params={"limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert len(body["runs"]) == 2


def test_status_rejects_invalid_limit(admin_client: TestClient) -> None:
    response = admin_client.get("/admin/ingest/status", params={"limit": 0})
    assert response.status_code == 422


def test_status_no_key_is_401(no_auth_client: TestClient) -> None:
    response = no_auth_client.get("/admin/ingest/status")
    assert response.status_code == 401


def test_status_non_admin_key_is_403(read_client: TestClient) -> None:
    response = read_client.get("/admin/ingest/status")
    assert response.status_code == 403
