"""Unit tests for ``GET /events`` (combined-filter route).

Drives the assembled ``Quake.app`` through a ``TestClient``. The
``EventsQuery`` validators (parsing ``near=lat,lon``, requiring
``near``/``radius_km`` together, rejecting naive datetimes) are
exercised here through real HTTP requests.

Every ``/events*`` route requires a valid API key (Epic 5 — Task 3);
the ``client`` fixture issues one against the sandbox DB + a
:class:`StubVault` and pre-loads the ``Authorization`` header so the
existing query/validation assertions need no further change.
``no_auth_client`` covers the 401 cases.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from database.etls.events import EventsETL
from database.models import EventRow
from quake.api.auth import get_vault_client
from quake.main import Quake
from tests._auth import StubVault, issue_test_key


def _event(
    event_id: str,
    *,
    time: datetime,
    magnitude: float = 4.0,
    latitude: float = 37.0,
    longitude: float = -122.0,
) -> EventRow:
    return EventRow(
        event_id=event_id,
        time=time,
        magnitude=magnitude,
        magnitude_type="md",
        depth_km=10.0,
        latitude=latitude,
        longitude=longitude,
        place="10km N of nowhere",
        status="reviewed",
        tsunami=False,
        url=f"https://earthquake.usgs.gov/earthquakes/eventpage/{event_id}",
        inserted_at=time,
        updated_at=time,
    )


@pytest.fixture
def client() -> TestClient:
    vault = StubVault()
    quake = Quake(logger=logging.getLogger("test-events-api-query"))
    quake.app.dependency_overrides[get_vault_client] = lambda: vault
    _, headers = issue_test_key(vault=vault)
    c = TestClient(quake.app)
    c.headers.update(headers)
    return c


@pytest.fixture
def no_auth_client() -> TestClient:
    """TestClient with no Authorization header — for the 401 cases."""
    vault = StubVault()
    quake = Quake(logger=logging.getLogger("test-events-api-query-noauth"))
    quake.app.dependency_overrides[get_vault_client] = lambda: vault
    return TestClient(quake.app)


@pytest.fixture
def events() -> EventsETL:
    return EventsETL()


def test_query_no_filters(client: TestClient, events: EventsETL) -> None:
    t0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    events.upsert(_event("a", time=t0))
    events.upsert(_event("b", time=t0 + timedelta(hours=1)))
    events.upsert(_event("c", time=t0 + timedelta(hours=2)))

    response = client.get("/events")
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 3
    assert {e["event_id"] for e in body["events"]} == {"a", "b", "c"}


def test_query_near_and_radius(client: TestClient, events: EventsETL) -> None:
    """Berkeley-centred 50 km circle — Oakland/SF in, Sacramento out."""
    events.upsert(
        _event("oakland", time=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc), latitude=37.80, longitude=-122.27)
    )
    events.upsert(
        _event("sf", time=datetime(2026, 5, 17, 12, 1, tzinfo=timezone.utc), latitude=37.77, longitude=-122.41)
    )
    events.upsert(
        _event("sacramento", time=datetime(2026, 5, 17, 12, 2, tzinfo=timezone.utc), latitude=38.58, longitude=-121.49)
    )

    response = client.get("/events", params={"near": "37.87,-122.27", "radius_km": 50})
    assert response.status_code == 200

    body = response.json()
    ids = {e["event_id"] for e in body["events"]}
    assert ids == {"oakland", "sf"}


def test_query_min_magnitude(client: TestClient, events: EventsETL) -> None:
    t0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    events.upsert(_event("small", time=t0, magnitude=2.0))
    events.upsert(_event("medium", time=t0 + timedelta(hours=1), magnitude=4.5))
    events.upsert(_event("large", time=t0 + timedelta(hours=2), magnitude=6.0))

    response = client.get("/events", params={"min_magnitude": 4.0})
    assert response.status_code == 200

    body = response.json()
    assert [e["event_id"] for e in body["events"]] == ["large", "medium"]


def test_query_since(client: TestClient, events: EventsETL) -> None:
    t0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    events.upsert(_event("old", time=t0, magnitude=5.0))
    events.upsert(_event("new", time=t0 + timedelta(hours=5), magnitude=5.0))

    response = client.get("/events", params={"since": (t0 + timedelta(hours=1)).isoformat()})
    assert response.status_code == 200

    body = response.json()
    assert [e["event_id"] for e in body["events"]] == ["new"]


def test_query_combined(client: TestClient, events: EventsETL) -> None:
    """All four filters together should narrow to exactly one row."""
    t0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    events.upsert(
        _event("small_nearby", time=t0 + timedelta(hours=3), magnitude=2.0, latitude=37.80, longitude=-122.27)
    )
    events.upsert(_event("old_nearby", time=t0, magnitude=5.0, latitude=37.80, longitude=-122.27))
    events.upsert(_event("far_strong", time=t0 + timedelta(hours=3), magnitude=5.0, latitude=38.58, longitude=-121.49))
    events.upsert(_event("match", time=t0 + timedelta(hours=3), magnitude=5.0, latitude=37.77, longitude=-122.41))

    response = client.get(
        "/events",
        params={
            "near": "37.87,-122.27",
            "radius_km": 50,
            "min_magnitude": 4.0,
            "since": (t0 + timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert [e["event_id"] for e in body["events"]] == ["match"]


def test_query_partial_near_is_422(client: TestClient) -> None:
    """`near` without `radius_km` (or vice versa) must be rejected."""
    response = client.get("/events", params={"near": "37.87,-122.27"})
    assert response.status_code == 422

    response = client.get("/events", params={"radius_km": 50})
    assert response.status_code == 422


def test_query_invalid_near_format_is_422(client: TestClient) -> None:
    response = client.get("/events", params={"near": "not-a-coord", "radius_km": 50})
    assert response.status_code == 422


def test_query_naive_since_is_422(client: TestClient) -> None:
    response = client.get("/events", params={"since": "2026-01-01T00:00:00"})
    assert response.status_code == 422


def test_query_requires_auth(no_auth_client: TestClient) -> None:
    response = no_auth_client.get("/events")
    assert response.status_code == 401


def test_query_rejects_bad_key(no_auth_client: TestClient) -> None:
    response = no_auth_client.get(
        "/events",
        headers={"Authorization": "Bearer qkf_deadbeef00000000000000000000beef"},
    )
    assert response.status_code == 401
