"""End-to-end smoke for the Epic-4 read API.

Bypasses the USGS ingestion path (Epic 3 already covers that) and seeds
events directly via ``EventsETL.upsert_many``. Then drives the full
``Quake`` FastAPI app through a ``TestClient`` and asserts that every
endpoint added in this epic responds end-to-end:

* ``/health``
* ``/env``
* ``/metrics``
* ``/events/recent``
* ``/events`` with ``min_magnitude`` and ``near=lat,lon&radius_km``

The goal is wire-up verification — the matrix coverage already lives in
the unit tests (``test_events_api_*.py``, ``test_main_api.py``,
``test_events_etl.py``). The single function keeps the TestClient and
seeded fixture in scope across every assertion.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from database.etls.events import EventsETL
from database.main import transaction
from database.models import EventRow
from quake.main import Quake

pytestmark = pytest.mark.integration

# Truncate set mirrors the unit conftest's, minus seeded fixtures the
# integration DB doesn't pre-populate.
_TRUNCATE_SQL = """
    TRUNCATE
        quake.events,
        quake.event_revisions,
        quake.ingestion_runs
    RESTART IDENTITY CASCADE
"""

# Anchor time for the seed set; absolute so newest/oldest ordering is
# fully deterministic regardless of when the suite runs.
_T0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)


def _event(
    event_id: str,
    *,
    time: datetime,
    magnitude: float,
    latitude: float,
    longitude: float,
) -> EventRow:
    return EventRow(
        event_id=event_id,
        time=time,
        magnitude=magnitude,
        magnitude_type="md",
        depth_km=10.0,
        latitude=latitude,
        longitude=longitude,
        place="seeded",
        status="reviewed",
        tsunami=False,
        url=f"https://earthquake.usgs.gov/earthquakes/eventpage/{event_id}",
        inserted_at=time,
        updated_at=time,
    )


@pytest.fixture
def clean_events() -> Iterator[None]:
    """TRUNCATE event-related tables so the seed below is the only data present."""
    with transaction() as conn:
        conn.execute(_TRUNCATE_SQL)
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(Quake(logger=logging.getLogger("test-read-api-integration")).app)


def test_read_api_end_to_end(client: TestClient, clean_events: None) -> None:
    """One pass covering every endpoint shipped in Epic 4."""
    # Seed three events that exercise both filters:
    #   seed_a — nearby (37.0, 23.0), magnitude below 5.0
    #   seed_b — nearby (37.0, 23.0), magnitude at/above 5.0
    #   seed_c — far away,             magnitude at/above 5.0
    EventsETL().upsert_many(
        [
            _event("seed_a", time=_T0, magnitude=4.0, latitude=37.0, longitude=23.0),
            _event("seed_b", time=_T0 + timedelta(hours=1), magnitude=5.5, latitude=37.0, longitude=23.0),
            _event("seed_c", time=_T0 + timedelta(hours=2), magnitude=6.0, latitude=50.0, longitude=-100.0),
        ]
    )

    # /health
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"]
    assert body["version"]

    # /env — integration conftest pins ENVIRONMENT=testing
    response = client.get("/env")
    assert response.status_code == 200
    body = response.json()
    assert body["environment"] == "testing"
    assert body["application_name"]
    assert body["version"]

    # /metrics — celery counter is registered via quake/api/main/__init__
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "celery_task_total" in response.text

    # /events/recent — two newest, in DESC time order
    response = client.get("/events/recent", params={"limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [e["event_id"] for e in body["events"]] == ["seed_c", "seed_b"]

    # /events?min_magnitude=5.0 — drops seed_a
    response = client.get("/events", params={"min_magnitude": 5.0})
    assert response.status_code == 200
    body = response.json()
    assert {e["event_id"] for e in body["events"]} == {"seed_b", "seed_c"}

    # /events?near=37.0,23.0&radius_km=200 — drops seed_c (far)
    response = client.get("/events", params={"near": "37.0,23.0", "radius_km": 200})
    assert response.status_code == 200
    body = response.json()
    assert {e["event_id"] for e in body["events"]} == {"seed_a", "seed_b"}
