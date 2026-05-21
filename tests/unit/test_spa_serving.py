"""Unit tests for SPA static serving + the index.html catch-all.

``Quake._mount_spa`` registers a catch-all *after* every API router, so the
built SPA is served at ``/`` and deep links resolve, while API and docs routes
keep matching first. These tests point ``_DIST_DIR`` at a throwaway build dir
(no real ``make frontend-build`` needed) and drive the assembled app through a
``TestClient``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quake import main as quake_main
from quake.api.auth import get_vault_client
from quake.main import Quake
from tests._auth import StubVault

_INDEX_HTML = "<!doctype html><html><body><div id='root'></div></body></html>"
_ASSET_JS = "console.log('quake-feed');"


@pytest.fixture
def spa_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Construct the app against a fake frontend/dist under tmp_path."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(_INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "app.js").write_text(_ASSET_JS, encoding="utf-8")

    # _mount_spa reads this at construction time, so patch before building Quake.
    monkeypatch.setattr(quake_main, "_DIST_DIR", dist)
    quake = Quake(logger=logging.getLogger("test-spa"))
    # The auth dependency resolves get_vault_client before the 401 check fires,
    # so stub it out (the events route's 401 case must not touch real Vault).
    quake.app.dependency_overrides[get_vault_client] = StubVault
    yield TestClient(quake.app)


def test_index_served_at_root(spa_client: TestClient) -> None:
    response = spa_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "id='root'" in response.text


def test_unknown_client_route_serves_index(spa_client: TestClient) -> None:
    """A deep link to a client-only route falls back to index.html (200)."""
    response = spa_client.get("/alerts")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "id='root'" in response.text


def test_hashed_asset_is_served_directly(spa_client: TestClient) -> None:
    response = spa_client.get("/assets/app.js")
    assert response.status_code == 200
    assert _ASSET_JS in response.text


def test_health_route_not_shadowed(spa_client: TestClient) -> None:
    """`/health` still resolves to the JSON API, not the SPA catch-all."""
    response = spa_client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["status"] == "ok"


def test_events_route_not_shadowed(spa_client: TestClient) -> None:
    """`/events/recent` is matched by the (auth-gated) events router → 401, not index.html."""
    response = spa_client.get("/events/recent")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")


def test_openapi_not_shadowed(spa_client: TestClient) -> None:
    """FastAPI's own /openapi.json keeps resolving ahead of the catch-all."""
    response = spa_client.get("/openapi.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
