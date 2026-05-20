"""Unit tests for the ``/alerts/filters`` Manager + Views.

Two-client matrix: ``client_a`` and ``client_b`` each carry a different
API key issued via :mod:`tests._auth`. Cross-key access (key B trying
to modify/delete one of key A's filters) is the load-bearing defence
test — the ETL enforces it via the ``api_key_id`` WHERE clause, the
view translates the ETL's ``False`` to ``404``, and these tests pin
the contract.
"""

from __future__ import annotations

import logging
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from database.etls.alert_filters import AlertFiltersETL
from database.etls.api_keys import ApiKeysETL
from quake.api.auth import get_vault_client, hash_key
from quake.main import Quake
from tests._auth import StubVault, issue_test_key


def _build(name: str) -> tuple[TestClient, StubVault]:
    vault = StubVault()
    quake = Quake(logger=logging.getLogger(name))
    quake.app.dependency_overrides[get_vault_client] = lambda: vault
    return TestClient(quake.app), vault


@pytest.fixture
def two_clients() -> Iterator[tuple[TestClient, str, int, TestClient, str, int]]:
    """Two TestClients sharing one StubVault — keys A and B both valid."""
    vault = StubVault()
    quake = Quake(logger=logging.getLogger("test-alert-filters-api"))
    quake.app.dependency_overrides[get_vault_client] = lambda: vault

    raw_a, headers_a = issue_test_key(vault=vault, scopes=[], label="key-a")
    raw_b, headers_b = issue_test_key(vault=vault, scopes=[], label="key-b")
    # The ETL needs the integer api_key_id, not the raw key.
    key_a_id = ApiKeysETL().get_by_hash(hash_key(raw_a))
    key_b_id = ApiKeysETL().get_by_hash(hash_key(raw_b))
    assert key_a_id is not None and key_b_id is not None

    client_a = TestClient(quake.app)
    client_a.headers.update(headers_a)
    client_b = TestClient(quake.app)
    client_b.headers.update(headers_b)
    yield client_a, raw_a, key_a_id.id, client_b, raw_b, key_b_id.id


@pytest.fixture
def no_auth_client() -> TestClient:
    client, _ = _build("test-alert-filters-noauth")
    return client


# ---------------------------------------------------------------------------
# GET /alerts/filters
# ---------------------------------------------------------------------------


def test_list_empty(two_clients: tuple[TestClient, str, int, TestClient, str, int]) -> None:
    client_a, _, _, _, _, _ = two_clients
    response = client_a.get("/alerts/filters")
    assert response.status_code == 200
    assert response.json() == {"count": 0, "filters": []}


def test_list_returns_only_this_keys_filters(two_clients: tuple[TestClient, str, int, TestClient, str, int]) -> None:
    client_a, _, key_a_id, client_b, _, key_b_id = two_clients
    AlertFiltersETL().insert(key_a_id, min_magnitude=3.0)
    AlertFiltersETL().insert(key_b_id, min_magnitude=5.5)

    body_a = client_a.get("/alerts/filters").json()
    assert body_a["count"] == 1
    assert body_a["filters"][0]["min_magnitude"] == 3.0

    body_b = client_b.get("/alerts/filters").json()
    assert body_b["count"] == 1
    assert body_b["filters"][0]["min_magnitude"] == 5.5


# ---------------------------------------------------------------------------
# POST /alerts/filters
# ---------------------------------------------------------------------------


def test_create_round_trip(two_clients: tuple[TestClient, str, int, TestClient, str, int]) -> None:
    client_a, _, key_a_id, _, _, _ = two_clients

    payload = {
        "min_magnitude": 4.0,
        "bbox_min_lat": 36.0,
        "bbox_min_lon": 22.0,
        "bbox_max_lat": 38.0,
        "bbox_max_lon": 24.0,
    }
    response = client_a.post("/alerts/filters", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["min_magnitude"] == 4.0
    assert body["bbox_min_lat"] == 36.0
    assert body["api_key_id"] == key_a_id
    assert body["id"] > 0
    assert "created_at" in body and "updated_at" in body

    # ETL agrees.
    rows = AlertFiltersETL().for_api_key(key_a_id)
    assert len(rows) == 1
    assert rows[0].id == body["id"]


def test_create_rejects_empty_filter(two_clients: tuple[TestClient, str, int, TestClient, str, int]) -> None:
    client_a, _, _, _, _, _ = two_clients
    response = client_a.post("/alerts/filters", json={})
    assert response.status_code == 422


def test_create_rejects_bbox_plus_center(two_clients: tuple[TestClient, str, int, TestClient, str, int]) -> None:
    client_a, _, _, _, _, _ = two_clients
    response = client_a.post(
        "/alerts/filters",
        json={
            "bbox_min_lat": 36.0,
            "bbox_min_lon": 22.0,
            "bbox_max_lat": 38.0,
            "bbox_max_lon": 24.0,
            "center_lat": 37.0,
            "center_lon": 23.0,
            "radius_km": 100.0,
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /alerts/filters/{id}
# ---------------------------------------------------------------------------


def test_update_replaces_fields(two_clients: tuple[TestClient, str, int, TestClient, str, int]) -> None:
    client_a, _, key_a_id, _, _, _ = two_clients
    fid = AlertFiltersETL().insert(key_a_id, min_magnitude=3.0)

    response = client_a.patch(
        f"/alerts/filters/{fid}",
        json={"min_magnitude": 6.0, "center_lat": 37.0, "center_lon": 23.0, "radius_km": 50.0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == fid
    assert body["min_magnitude"] == 6.0
    assert body["center_lat"] == 37.0
    assert body["radius_km"] == 50.0


def test_update_unknown_filter_is_404(two_clients: tuple[TestClient, str, int, TestClient, str, int]) -> None:
    client_a, _, _, _, _, _ = two_clients
    response = client_a.patch(
        "/alerts/filters/9999",
        json={"min_magnitude": 4.0},
    )
    assert response.status_code == 404


def test_update_foreign_filter_is_404(two_clients: tuple[TestClient, str, int, TestClient, str, int]) -> None:
    """Key B cannot update a filter owned by key A — the ETL's WHERE catches it."""
    _, _, key_a_id, client_b, _, _ = two_clients
    fid_a = AlertFiltersETL().insert(key_a_id, min_magnitude=3.0)

    response = client_b.patch(
        f"/alerts/filters/{fid_a}",
        json={"min_magnitude": 9.9},
    )
    assert response.status_code == 404

    # Defence-in-depth: row was NOT mutated.
    rows = AlertFiltersETL().for_api_key(key_a_id)
    assert rows[0].min_magnitude == 3.0


# ---------------------------------------------------------------------------
# DELETE /alerts/filters/{id}
# ---------------------------------------------------------------------------


def test_delete_removes_row(two_clients: tuple[TestClient, str, int, TestClient, str, int]) -> None:
    client_a, _, key_a_id, _, _, _ = two_clients
    fid = AlertFiltersETL().insert(key_a_id, min_magnitude=3.0)

    response = client_a.delete(f"/alerts/filters/{fid}")
    assert response.status_code == 204
    assert response.content == b""  # 204 with empty body

    assert AlertFiltersETL().for_api_key(key_a_id) == []


def test_delete_unknown_filter_is_404(two_clients: tuple[TestClient, str, int, TestClient, str, int]) -> None:
    client_a, _, _, _, _, _ = two_clients
    response = client_a.delete("/alerts/filters/9999")
    assert response.status_code == 404


def test_delete_foreign_filter_is_404(two_clients: tuple[TestClient, str, int, TestClient, str, int]) -> None:
    _, _, key_a_id, client_b, _, _ = two_clients
    fid_a = AlertFiltersETL().insert(key_a_id, min_magnitude=3.0)

    response = client_b.delete(f"/alerts/filters/{fid_a}")
    assert response.status_code == 404

    # Row still present.
    assert len(AlertFiltersETL().for_api_key(key_a_id)) == 1


# ---------------------------------------------------------------------------
# auth gating
# ---------------------------------------------------------------------------


def test_list_without_auth_is_401(no_auth_client: TestClient) -> None:
    assert no_auth_client.get("/alerts/filters").status_code == 401


def test_create_without_auth_is_401(no_auth_client: TestClient) -> None:
    assert no_auth_client.post("/alerts/filters", json={"min_magnitude": 4.0}).status_code == 401


def test_update_without_auth_is_401(no_auth_client: TestClient) -> None:
    assert no_auth_client.patch("/alerts/filters/1", json={"min_magnitude": 4.0}).status_code == 401


def test_delete_without_auth_is_401(no_auth_client: TestClient) -> None:
    assert no_auth_client.delete("/alerts/filters/1").status_code == 401
