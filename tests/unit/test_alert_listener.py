"""Unit tests for :class:`quake.alerts.listener.AlertListener`.

Exercises the real wiring against the sandbox DB from
``tests/unit/conftest.py``:

1. The ``20260519154655_events_notify.sql`` migration installs the
   trigger that fires ``pg_notify`` on every ``quake.events`` INSERT.
2. The listener opens a long-lived async psycopg connection, issues
   ``LISTEN quake_event_inserts``, decodes payloads, and publishes
   :class:`EventRow` envelopes through a fresh
   :class:`SubscriberRegistry` (not the module-level singleton, so each
   test is hermetic).

Each test:

* spins up a fresh ``SubscriberRegistry`` + ``AlertListener``,
* subscribes one slot with a wide filter so every test event matches,
* starts ``listener.run()`` as an ``asyncio.Task``,
* ``await listener.ready.wait()`` before triggering work, so the LISTEN
  is in place before the INSERT,
* asserts on what the subscriber's queue received,
* calls ``listener.stop()`` and awaits the task in a ``finally``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from database.etls.events import EventsETL
from database.main import transaction
from database.models import AlertFilterRow, EventRow
from models.alerts import AlertEnvelope
from quake.alerts.listener import AlertListener
from quake.alerts.registry import Subscriber, SubscriberRegistry

_NOW = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


def _event(event_id: str, *, magnitude: float = 5.0) -> EventRow:
    return EventRow(
        event_id=event_id,
        time=_NOW,
        magnitude=magnitude,
        magnitude_type="md",
        depth_km=10.0,
        latitude=37.0,
        longitude=23.0,
        place="testland",
        status="reviewed",
        tsunami=False,
        url=None,
        inserted_at=_NOW,
        updated_at=_NOW,
    )


def _wide_filter() -> AlertFilterRow:
    """A filter that matches every event the tests insert (mag >= 0)."""
    return AlertFilterRow(
        id=1,
        api_key_id=1,
        min_magnitude=0.0,
        bbox_min_lat=None,
        bbox_min_lon=None,
        bbox_max_lat=None,
        bbox_max_lon=None,
        center_lat=None,
        center_lon=None,
        radius_km=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest_asyncio.fixture
async def listener_and_sub() -> AsyncIterator[tuple[AlertListener, Subscriber]]:
    """Spin up a listener + subscriber, tear them down cleanly after the test."""
    registry = SubscriberRegistry()
    sub = registry.subscribe(api_key_id=1, filters=[_wide_filter()])
    listener = AlertListener(registry=registry)
    task = asyncio.create_task(listener.run())
    try:
        await asyncio.wait_for(listener.ready.wait(), timeout=5.0)
        yield listener, sub
    finally:
        listener.stop()
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# ---------------------------------------------------------------------------
# happy path — trigger fires, listener delivers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_fires_notify_and_listener_publishes_envelope(
    listener_and_sub: tuple[AlertListener, Subscriber],
) -> None:
    """One INSERT into quake.events → exactly one envelope on the subscriber queue."""
    _listener, sub = listener_and_sub

    EventsETL().upsert_many([_event("ev_001", magnitude=5.5)])

    envelope = await asyncio.wait_for(sub.queue.get(), timeout=5.0)
    assert isinstance(envelope, AlertEnvelope)
    assert envelope.event_id == "ev_001"
    assert envelope.magnitude == 5.5
    assert envelope.latitude == 37.0


# ---------------------------------------------------------------------------
# robustness — malformed payload doesn't take down the listener
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_payload_is_skipped_and_next_event_still_delivers(
    listener_and_sub: tuple[AlertListener, Subscriber],
) -> None:
    """Operator noise on the channel must not kill the listener task."""
    _listener, sub = listener_and_sub

    # Inject garbage directly on the channel — no JSON shape, no event row.
    with transaction() as conn:
        conn.execute("SELECT pg_notify('quake_event_inserts', 'not json at all')")

    # The listener should have logged and moved on. A valid INSERT now
    # still delivers, proving the task survived the bad payload.
    EventsETL().upsert_many([_event("ev_after_garbage", magnitude=4.0)])

    envelope = await asyncio.wait_for(sub.queue.get(), timeout=5.0)
    assert envelope.event_id == "ev_after_garbage"


@pytest.mark.asyncio
async def test_json_with_wrong_shape_is_skipped_and_next_event_still_delivers(
    listener_and_sub: tuple[AlertListener, Subscriber],
) -> None:
    """Valid JSON but not an events row → logged + skipped, listener survives."""
    _listener, sub = listener_and_sub

    with transaction() as conn:
        conn.execute("SELECT pg_notify('quake_event_inserts', '{\"hello\": \"world\"}')")

    EventsETL().upsert_many([_event("ev_after_bad_shape", magnitude=4.0)])

    envelope = await asyncio.wait_for(sub.queue.get(), timeout=5.0)
    assert envelope.event_id == "ev_after_bad_shape"


# ---------------------------------------------------------------------------
# batched inserts — one NOTIFY per row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batched_inserts_fire_one_notify_per_row(
    listener_and_sub: tuple[AlertListener, Subscriber],
) -> None:
    """EventsETL.upsert_many of N rows → N envelopes on the subscriber queue."""
    _listener, sub = listener_and_sub

    EventsETL().upsert_many(
        [
            _event("ev_batch_a", magnitude=3.0),
            _event("ev_batch_b", magnitude=4.0),
            _event("ev_batch_c", magnitude=5.0),
        ]
    )

    received: list[str] = []
    for _ in range(3):
        env = await asyncio.wait_for(sub.queue.get(), timeout=5.0)
        received.append(env.event_id)

    assert set(received) == {"ev_batch_a", "ev_batch_b", "ev_batch_c"}
    # No spurious extra deliveries.
    assert sub.queue.qsize() == 0
