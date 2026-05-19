"""End-to-end smoke for the Epic-5 auth + admin surface.

Drives the full ``Quake`` FastAPI app through a ``TestClient`` and walks
the scope ladder + the ingestion lock kill-switch through the live admin
endpoints. The point is wire-up verification across modules — the matrix
coverage already lives in the unit tests (``test_auth.py``,
``test_locks_api.py``, ``test_ingest_api.py``).

Two test-isolation tricks worth calling out:

* **Vault**: a :class:`tests._auth.StubVault` is injected via
  ``app.dependency_overrides[get_vault_client]`` so the test never talks
  to the live Vault container. Auth itself is a real path — DB rows are
  inserted, ``Authenticate`` resolves them.
* **Celery ``send_task``**: monkey-patched to invoke
  ``celery_app.tasks[name].apply()`` synchronously. ``task_always_eager``
  is **not** honoured by Celery's ``send_task`` (see its 5.x docstring —
  "task_always_eager has no effect on send_task"), so the only reliable
  way to exercise the trigger path end-to-end is to short-circuit the
  dispatch. The trigger view's contract is otherwise unchanged: it still
  returns an ``AsyncResult`` with an ``.id``, just produced by ``apply``.
* **USGS**: ``UsgsClient.fetch`` is monkey-patched to return an empty
  payload so the second (unlocked) trigger doesn't touch the network and
  the test stays deterministic + offline-capable.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from celery.result import EagerResult
from fastapi.testclient import TestClient

from config import celery_app
from database.etls.endpoint_locks import EndpointLocksETL
from database.etls.ingestion_runs import IngestionRunsETL
from database.main import transaction
from quake.api.auth import get_vault_client
from quake.ingestion.usgs.client import UsgsClient
from quake.main import Quake
from tests._auth import StubVault, issue_test_key

# Make sure the @celery_app.task decorators fire so ``poll_usgs`` is
# registered under ``celery_app.tasks`` before send_task is patched.
importlib.import_module("quake.tasks")

pytestmark = pytest.mark.integration

_POLL_TASK_NAME = "quake.tasks.poll_usgs"

# Same truncate set as ``tests/integration/test_read_api.py`` + an
# explicit clear of INGESTION_LOCK so the kill-switch always starts open
# even when a previous integration test left it set.
_TRUNCATE_SQL = """
    TRUNCATE
        quake.events,
        quake.event_revisions,
        quake.ingestion_runs,
        quake.api_keys
    RESTART IDENTITY CASCADE
"""


@pytest.fixture
def clean_admin_state() -> Iterator[None]:
    """TRUNCATE the per-test tables and reset INGESTION_LOCK to cleared."""
    with transaction() as conn:
        conn.execute(_TRUNCATE_SQL)
    EndpointLocksETL().clear_lock("INGESTION_LOCK")
    yield


@pytest.fixture
def app_client(clean_admin_state: None) -> tuple[TestClient, StubVault]:
    """A bare ``TestClient`` + the StubVault override (no preset auth header)."""
    vault = StubVault()
    quake = Quake(logger=logging.getLogger("test-auth-admin-integration"))
    quake.app.dependency_overrides[get_vault_client] = lambda: vault
    return TestClient(quake.app), vault


@pytest.fixture
def synchronous_send_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``celery_app.send_task`` run the task synchronously via ``apply``.

    See the module docstring for the rationale. ``apply`` returns an
    :class:`celery.result.EagerResult` whose ``.id`` matches the trigger
    view's response shape, so no view-side changes are needed.
    """

    def _eager_send_task(name: str, *_args: Any, **_kwargs: Any) -> EagerResult:
        task = celery_app.tasks[name]
        return task.apply()

    monkeypatch.setattr(celery_app, "send_task", _eager_send_task)


@pytest.fixture
def stub_usgs_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``UsgsClient.fetch`` with an empty-feed payload (no network)."""

    def _empty_fetch(self: UsgsClient, feed: Any) -> dict[str, Any]:
        return {"type": "FeatureCollection", "features": []}

    monkeypatch.setattr(UsgsClient, "fetch", _empty_fetch)


def test_auth_and_admin_surface_end_to_end(
    app_client: tuple[TestClient, StubVault],
    synchronous_send_task: None,
    stub_usgs_fetch: None,
) -> None:
    """One pass exercising the scope ladder + the INGESTION_LOCK kill-switch."""
    client, vault = app_client

    # ── 1) read key: any-key route OK, admin route forbidden ───────────
    _, read_headers = issue_test_key(vault=vault, scopes=[], label="read")

    response = client.get("/events/recent", headers=read_headers, params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0  # DB was truncated; no events seeded
    assert body["events"] == []

    response = client.get("/admin/locks", headers=read_headers)
    assert response.status_code == 403

    # ── 2) admin key: both tiers pass ─────────────────────────────────
    _, admin_headers = issue_test_key(vault=vault, scopes=["admin"], label="admin")

    response = client.get("/events/recent", headers=admin_headers, params={"limit": 5})
    assert response.status_code == 200

    response = client.get("/admin/locks", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    # INGESTION_LOCK was reset to cleared by the fixture.
    locks_by_name = {lk["lock_name"]: lk for lk in body["locks"]}
    assert "INGESTION_LOCK" in locks_by_name
    assert locks_by_name["INGESTION_LOCK"]["is_locked"] is False

    # ── 3) set INGESTION_LOCK via /admin/locks ────────────────────────
    response = client.post(
        "/admin/locks/INGESTION_LOCK",
        headers=admin_headers,
        json={"locked_by": "integration-test", "reason": "smoke"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_locked"] is True
    assert body["locked_by"] == "integration-test"
    assert body["reason"] == "smoke"

    # ── 4) trigger with lock set → task records a skip-marker run ────
    response = client.post("/admin/ingest/trigger", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    skip_task_id = body["task_id"]
    assert skip_task_id

    # The synchronously-applied task wrote one ingestion_runs row with
    # the skip envelope.
    response = client.get("/admin/ingest/status", headers=admin_headers, params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["runs"][0]["error"] == "INGESTION_LOCK active"
    assert body["runs"][0]["inserted_count"] == 0
    assert body["runs"][0]["updated_count"] == 0
    assert body["runs"][0]["revision_count"] == 0

    # ── 5) clear INGESTION_LOCK ────────────────────────────────────────
    response = client.delete("/admin/locks/INGESTION_LOCK", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["is_locked"] is False

    # ── 6) trigger again → task runs the real poll path (stubbed USGS) ─
    response = client.post("/admin/ingest/trigger", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    run_task_id = body["task_id"]
    assert run_task_id
    assert run_task_id != skip_task_id

    # Newest run is the just-completed real poll; previous is the skip.
    response = client.get("/admin/ingest/status", headers=admin_headers, params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    newest, previous = body["runs"][0], body["runs"][1]
    assert newest["error"] is None  # real poll, empty feed, no error
    assert newest["inserted_count"] == 0
    assert newest["updated_count"] == 0
    assert previous["error"] == "INGESTION_LOCK active"

    # Belt-and-braces: ETL agrees with the API response.
    db_runs = IngestionRunsETL().latest(5)
    assert len(db_runs) == 2
    assert db_runs[0].error is None
    assert db_runs[1].error == "INGESTION_LOCK active"

    # ── 7) revoke the admin key → 401 on the next /admin/locks call ──
    # Find the admin key's id (label="admin") and revoke it.
    with transaction() as conn:
        row = conn.execute(
            "SELECT id FROM quake.api_keys WHERE label = %s",
            ("admin",),
        ).fetchone()
        assert row is not None
        admin_key_id = row[0]
    from database.etls.api_keys import ApiKeysETL

    ApiKeysETL().revoke(admin_key_id)

    response = client.get("/admin/locks", headers=admin_headers)
    assert response.status_code == 401
