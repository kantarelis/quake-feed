"""Unit tests for the ``/admin/locks`` Manager + Views.

Three fixture flavours mirror the EventsManager test pattern:

* ``admin_client`` — TestClient with an issued admin-scoped key
  pre-loaded in the ``Authorization`` header.
* ``read_client`` — TestClient with a key that has no scopes; for the
  403 path.
* ``no_auth_client`` — TestClient with no header; for the 401 path.

All three share the same Vault override so no live Vault container is
touched.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from database.etls.endpoint_locks import EndpointLocksETL
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
    client, vault = _build("test-locks-api-admin")
    _, headers = issue_test_key(vault=vault, scopes=["admin"])
    client.headers.update(headers)
    return client


@pytest.fixture
def read_client() -> TestClient:
    client, vault = _build("test-locks-api-read")
    _, headers = issue_test_key(vault=vault, scopes=[])
    client.headers.update(headers)
    return client


@pytest.fixture
def no_auth_client() -> TestClient:
    client, _ = _build("test-locks-api-noauth")
    return client


# ---------------------------------------------------------------------------
# happy path (admin)
# ---------------------------------------------------------------------------


def test_list_locks_admin(admin_client: TestClient) -> None:
    """Seeded INGESTION_LOCK is visible; is_locked=false out of the box."""
    response = admin_client.get("/admin/locks")
    assert response.status_code == 200

    body = response.json()
    names = {lock["lock_name"] for lock in body["locks"]}
    assert "INGESTION_LOCK" in names
    seeded = next(lock for lock in body["locks"] if lock["lock_name"] == "INGESTION_LOCK")
    assert seeded["is_locked"] is False
    assert body["count"] == len(body["locks"])


def test_set_lock_admin(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/admin/locks/INGESTION_LOCK",
        json={"locked_by": "alice", "reason": "maintenance"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["lock_name"] == "INGESTION_LOCK"
    assert body["is_locked"] is True
    assert body["locked_by"] == "alice"
    assert body["reason"] == "maintenance"
    assert body["locked_at"] is not None

    # Cross-check via the ETL.
    assert EndpointLocksETL().is_locked("INGESTION_LOCK") is True


def test_clear_lock_admin(admin_client: TestClient) -> None:
    EndpointLocksETL().set_lock("INGESTION_LOCK", locked_by="alice", reason="x")

    response = admin_client.delete("/admin/locks/INGESTION_LOCK")
    assert response.status_code == 200

    body = response.json()
    assert body["is_locked"] is False
    assert body["locked_by"] is None
    assert body["reason"] is None
    assert body["locked_at"] is None

    assert EndpointLocksETL().is_locked("INGESTION_LOCK") is False


def test_unknown_lock_set_is_404(admin_client: TestClient) -> None:
    """Locks are seeded by migration — POST against an unknown name is a 404, not auto-create."""
    response = admin_client.post(
        "/admin/locks/DOES_NOT_EXIST",
        json={"locked_by": "alice", "reason": "x"},
    )
    assert response.status_code == 404
    assert "no such lock" in response.json()["detail"]


def test_unknown_lock_clear_is_404(admin_client: TestClient) -> None:
    response = admin_client.delete("/admin/locks/DOES_NOT_EXIST")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# auth boundary
# ---------------------------------------------------------------------------


def test_list_locks_no_key_is_401(no_auth_client: TestClient) -> None:
    response = no_auth_client.get("/admin/locks")
    assert response.status_code == 401


def test_list_locks_non_admin_key_is_403(read_client: TestClient) -> None:
    response = read_client.get("/admin/locks")
    assert response.status_code == 403


def test_set_lock_non_admin_key_is_403(read_client: TestClient) -> None:
    response = read_client.post(
        "/admin/locks/INGESTION_LOCK",
        json={"locked_by": "alice", "reason": "x"},
    )
    assert response.status_code == 403
