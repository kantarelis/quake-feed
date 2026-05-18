"""Unit tests for ``GET /events/recent``.

Drives the assembled ``Quake.app`` through a ``TestClient`` so the route
is exercised end-to-end through FastAPI's dependency-resolution machinery
(query-param parsing, ``RecentEventsQuery`` validation, the ``EventsETL``
call, response serialization). The sandbox DB conftest seeds an empty
``quake.events`` before each test.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from database.etls.events import EventsETL
from database.models import EventRow
from quake.main import Quake


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
    quake = Quake(logger=logging.getLogger("test-events-api"))
    return TestClient(quake.app)


@pytest.fixture
def events() -> EventsETL:
    return EventsETL()


def test_recent_returns_seeded_events_newest_first(client: TestClient, events: EventsETL) -> None:
    t0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    events.upsert(_event("oldest", time=t0))
    events.upsert(_event("middle", time=t0 + timedelta(hours=1)))
    events.upsert(_event("newest", time=t0 + timedelta(hours=2)))

    response = client.get("/events/recent")
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 3
    assert [e["event_id"] for e in body["events"]] == ["newest", "middle", "oldest"]


def test_recent_respects_limit(client: TestClient, events: EventsETL) -> None:
    t0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        events.upsert(_event(f"e{i}", time=t0 + timedelta(minutes=i)))

    response = client.get("/events/recent", params={"limit": 2})
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 2
    assert len(body["events"]) == 2


def test_recent_rejects_invalid_limit(client: TestClient) -> None:
    response = client.get("/events/recent", params={"limit": 0})
    assert response.status_code == 422


def test_recent_empty(client: TestClient) -> None:
    response = client.get("/events/recent")
    assert response.status_code == 200
    assert response.json() == {"count": 0, "events": []}
