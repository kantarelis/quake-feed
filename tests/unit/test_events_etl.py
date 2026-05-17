"""Unit tests for EventsETL.

Exercises the four scenarios called out in PLAN.md Task 5, plus a light
sanity layer for the read methods (get_by_id / recent / by_magnitude /
near). Revisions are cross-checked via RevisionsETL — there is no
separate revisions test file because the trigger is exercised
end-to-end here.

Tests run against the session-scoped sandbox container from
``tests/conftest.py``. Each test starts with empty tables (see
``_clean_tables`` in conftest).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database.etls.events import EventsETL
from database.etls.revisions import RevisionsETL
from database.models import EventRow


def _event(
    event_id: str = "nc0001",
    *,
    time: datetime | None = None,
    magnitude: float = 4.0,
    depth_km: float | None = 10.0,
    place: str | None = "10km N of nowhere",
    latitude: float = 37.0,
    longitude: float = -122.0,
) -> EventRow:
    now = datetime.now(timezone.utc)
    return EventRow(
        event_id=event_id,
        time=time or now,
        magnitude=magnitude,
        magnitude_type="md",
        depth_km=depth_km,
        latitude=latitude,
        longitude=longitude,
        place=place,
        status="reviewed",
        tsunami=False,
        url=f"https://earthquake.usgs.gov/earthquakes/eventpage/{event_id}",
        inserted_at=now,
        updated_at=now,
    )


@pytest.fixture
def events() -> EventsETL:
    return EventsETL()


@pytest.fixture
def revisions() -> RevisionsETL:
    return RevisionsETL()


# ---------------------------------------------------------------------------
# upsert
# ---------------------------------------------------------------------------


def test_upsert_new_event_returns_inserted(events: EventsETL) -> None:
    outcome = events.upsert(_event())
    assert outcome == "inserted"


def test_upsert_same_pk_same_data_returns_updated(events: EventsETL) -> None:
    """Plan: 'pick once and stick' between 'unchanged' and 'updated'. We picked 'updated'.

    An UPSERT on an existing (event_id, time) always runs the UPDATE — the
    DB-level revision trigger handles whether that UPDATE represents an
    actually-meaningful change.
    """
    ev = _event()
    assert events.upsert(ev) == "inserted"
    assert events.upsert(ev) == "updated"


def test_upsert_above_threshold_writes_one_revision(events: EventsETL, revisions: RevisionsETL) -> None:
    """A magnitude shift of 0.2 (>= 0.1 threshold) must produce exactly one revision row."""
    base = _event(magnitude=4.0)
    events.upsert(base)

    bumped = _event(time=base.time, magnitude=4.2)  # same PK, magnitude +0.2
    events.upsert(bumped)

    revs = revisions.for_event(base.event_id)
    assert len(revs) == 1
    assert revs[0].old_magnitude == 4.0
    assert revs[0].new_magnitude == 4.2


def test_upsert_below_threshold_writes_no_revision(events: EventsETL, revisions: RevisionsETL) -> None:
    """Sub-threshold magnitude shift (0.05) must not produce a revision row."""
    base = _event(magnitude=4.0)
    events.upsert(base)
    events.upsert(_event(time=base.time, magnitude=4.05))

    assert revisions.for_event(base.event_id) == []


# ---------------------------------------------------------------------------
# upsert_many
# ---------------------------------------------------------------------------


def test_upsert_many_counts_inserts_and_updates(events: EventsETL) -> None:
    a = _event("a")
    b = _event("b", time=a.time + timedelta(minutes=1))

    first = events.upsert_many([a, b])
    assert first == {"inserted": 2, "updated": 0}

    second = events.upsert_many([a, _event("c", time=a.time + timedelta(minutes=2))])
    assert second == {"inserted": 1, "updated": 1}


# ---------------------------------------------------------------------------
# read methods — light sanity
# ---------------------------------------------------------------------------


def test_recent_orders_by_time_desc(events: EventsETL) -> None:
    """Plan scenario 4: recent(N) returns events in time DESC order."""
    t0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    events.upsert(_event("oldest", time=t0))
    events.upsert(_event("middle", time=t0 + timedelta(hours=1)))
    events.upsert(_event("newest", time=t0 + timedelta(hours=2)))

    out = events.recent(5)
    assert [e.event_id for e in out] == ["newest", "middle", "oldest"]


def test_recent_respects_limit(events: EventsETL) -> None:
    t0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        events.upsert(_event(f"e{i}", time=t0 + timedelta(minutes=i)))

    assert len(events.recent(3)) == 3


def test_get_by_id_returns_freshest_row(events: EventsETL) -> None:
    """When the same event_id has multiple time rows, get_by_id returns the latest."""
    t0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    events.upsert(_event("nc0001", time=t0, magnitude=3.0))
    events.upsert(_event("nc0001", time=t0 + timedelta(minutes=5), magnitude=3.5))

    out = events.get_by_id("nc0001")
    assert out is not None
    assert out.time == t0 + timedelta(minutes=5)
    assert out.magnitude == 3.5


def test_get_by_id_missing_returns_none(events: EventsETL) -> None:
    assert events.get_by_id("does-not-exist") is None


def test_by_magnitude_filters_and_orders(events: EventsETL) -> None:
    t0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    events.upsert(_event("small", time=t0, magnitude=2.0))
    events.upsert(_event("medium", time=t0 + timedelta(hours=1), magnitude=4.5))
    events.upsert(_event("large", time=t0 + timedelta(hours=2), magnitude=6.0))

    out = events.by_magnitude(4.0)
    assert [e.event_id for e in out] == ["large", "medium"]


def test_by_magnitude_since_bound(events: EventsETL) -> None:
    t0 = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    events.upsert(_event("old", time=t0, magnitude=5.0))
    events.upsert(_event("new", time=t0 + timedelta(hours=5), magnitude=5.0))

    out = events.by_magnitude(4.0, since=t0 + timedelta(hours=1))
    assert [e.event_id for e in out] == ["new"]


def test_near_includes_close_excludes_far(events: EventsETL) -> None:
    """Hayward fault region — close events should land inside a 50 km radius."""
    # Reference point: Berkeley, CA (37.87, -122.27)
    events.upsert(_event("oakland", latitude=37.80, longitude=-122.27))  # ~8 km south
    events.upsert(_event("sf", latitude=37.77, longitude=-122.41))  # ~17 km
    events.upsert(_event("sacramento", latitude=38.58, longitude=-121.49))  # ~120 km

    out = events.near(lat=37.87, lon=-122.27, radius_km=50)
    ids = {e.event_id for e in out}
    assert "oakland" in ids
    assert "sf" in ids
    assert "sacramento" not in ids
