"""Unit tests for :mod:`quake.alerts.registry`.

Exercises the in-process bus end-to-end with a real
:class:`FilterMatcher` and real :class:`AlertFilterRow` /
:class:`EventRow` shapes. No DB, no I/O — the registry is pure async.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterator

import pytest

from database.models import AlertFilterRow, EventRow
from models.alerts import AlertEnvelope
from quake.alerts.registry import (
    Subscriber,
    SubscriberRegistry,
    get_registry,
    reset_registry_for_tests,
)

_NOW = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# row + event helpers
# ---------------------------------------------------------------------------


def _filter(
    *,
    id: int = 1,
    api_key_id: int = 1,
    min_magnitude: float | None = None,
    bbox_min_lat: float | None = None,
    bbox_min_lon: float | None = None,
    bbox_max_lat: float | None = None,
    bbox_max_lon: float | None = None,
) -> AlertFilterRow:
    return AlertFilterRow(
        id=id,
        api_key_id=api_key_id,
        min_magnitude=min_magnitude,
        bbox_min_lat=bbox_min_lat,
        bbox_min_lon=bbox_min_lon,
        bbox_max_lat=bbox_max_lat,
        bbox_max_lon=bbox_max_lon,
        center_lat=None,
        center_lon=None,
        radius_km=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _event(*, magnitude: float = 5.0, latitude: float = 37.0, longitude: float = 23.0) -> EventRow:
    return EventRow(
        event_id="ev_test",
        time=_NOW,
        magnitude=magnitude,
        magnitude_type="md",
        depth_km=10.0,
        latitude=latitude,
        longitude=longitude,
        place="testland",
        status="reviewed",
        tsunami=False,
        url=None,
        inserted_at=_NOW,
        updated_at=_NOW,
    )


@pytest.fixture
def reset_registry() -> Iterator[None]:
    """Drop the module-level singleton around each test."""
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


# ---------------------------------------------------------------------------
# subscribe / unsubscribe / get_subscriber_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_returns_distinct_ids_and_queue() -> None:
    reg = SubscriberRegistry()
    a = reg.subscribe(api_key_id=1, filters=[_filter(min_magnitude=4.0)])
    b = reg.subscribe(api_key_id=2, filters=[_filter(min_magnitude=4.0)])

    assert isinstance(a, Subscriber)
    assert a.id != b.id
    assert isinstance(a.queue, asyncio.Queue)
    assert reg.get_subscriber_count() == 2


@pytest.mark.asyncio
async def test_unsubscribe_removes_slot() -> None:
    reg = SubscriberRegistry()
    sub = reg.subscribe(api_key_id=1, filters=[_filter(min_magnitude=4.0)])
    reg.unsubscribe(sub.id)
    assert reg.get_subscriber_count() == 0


@pytest.mark.asyncio
async def test_unsubscribe_unknown_id_is_noop() -> None:
    reg = SubscriberRegistry()
    reg.unsubscribe(9999)  # no error
    assert reg.get_subscriber_count() == 0


# ---------------------------------------------------------------------------
# publish — routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_routes_to_matching_subscriber() -> None:
    reg = SubscriberRegistry()
    sub = reg.subscribe(api_key_id=1, filters=[_filter(min_magnitude=4.0)])
    reg.publish(_event(magnitude=5.0))

    envelope = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
    assert isinstance(envelope, AlertEnvelope)
    assert envelope.event_id == "ev_test"
    assert envelope.magnitude == 5.0


@pytest.mark.asyncio
async def test_publish_skips_non_matching_subscriber() -> None:
    reg = SubscriberRegistry()
    sub = reg.subscribe(api_key_id=1, filters=[_filter(min_magnitude=6.0)])
    reg.publish(_event(magnitude=5.0))

    # Queue stays empty; a get() should timeout.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.queue.get(), timeout=0.05)


@pytest.mark.asyncio
async def test_publish_ors_across_multiple_filters_for_one_subscriber() -> None:
    """A subscriber with two filters receives the event if ANY filter matches."""
    reg = SubscriberRegistry()
    sub = reg.subscribe(
        api_key_id=1,
        filters=[
            _filter(id=1, min_magnitude=6.0),  # won't match a mag-5 event
            _filter(id=2, min_magnitude=4.0),  # will match
        ],
    )
    reg.publish(_event(magnitude=5.0))

    envelope = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
    assert envelope.event_id == "ev_test"


@pytest.mark.asyncio
async def test_publish_delivers_exactly_once_when_multiple_filters_all_match() -> None:
    """Two filters that both match the same event → still one envelope in the queue."""
    reg = SubscriberRegistry()
    sub = reg.subscribe(
        api_key_id=1,
        filters=[
            _filter(id=1, min_magnitude=4.0),
            _filter(id=2, min_magnitude=3.0),
        ],
    )
    reg.publish(_event(magnitude=5.0))

    await asyncio.wait_for(sub.queue.get(), timeout=1.0)
    assert sub.queue.qsize() == 0  # no duplicate


@pytest.mark.asyncio
async def test_publish_skips_subscriber_with_empty_filter_list() -> None:
    """An empty filter list never matches anything."""
    reg = SubscriberRegistry()
    sub = reg.subscribe(api_key_id=1, filters=[])
    reg.publish(_event(magnitude=5.0))

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.queue.get(), timeout=0.05)


@pytest.mark.asyncio
async def test_publish_routes_to_multiple_matching_subscribers() -> None:
    """Different keys, both matching → both receive the envelope."""
    reg = SubscriberRegistry()
    a = reg.subscribe(api_key_id=1, filters=[_filter(min_magnitude=4.0)])
    b = reg.subscribe(api_key_id=2, filters=[_filter(min_magnitude=4.0)])
    reg.publish(_event(magnitude=5.0))

    envelope_a = await asyncio.wait_for(a.queue.get(), timeout=1.0)
    envelope_b = await asyncio.wait_for(b.queue.get(), timeout=1.0)
    assert envelope_a.event_id == envelope_b.event_id == "ev_test"


# ---------------------------------------------------------------------------
# publish — back-pressure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_drops_envelope_when_queue_full_and_keeps_going() -> None:
    """Slow subscriber gets envelopes dropped; other subscribers still receive."""
    reg = SubscriberRegistry(queue_maxsize=1)
    slow = reg.subscribe(api_key_id=1, filters=[_filter(min_magnitude=4.0)])
    fast = reg.subscribe(api_key_id=2, filters=[_filter(min_magnitude=4.0)])

    # Fill the slow subscriber's queue to capacity by hand.
    slow.queue.put_nowait(AlertEnvelope.model_validate(_event(magnitude=4.0)))
    assert slow.queue.full()

    # Now publish — slow.queue overflows (drop), fast.queue gets the envelope.
    reg.publish(_event(magnitude=5.0))

    # Slow: still holds the first envelope; the new one was dropped.
    held = await asyncio.wait_for(slow.queue.get(), timeout=1.0)
    assert held.magnitude == 4.0
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(slow.queue.get(), timeout=0.05)

    # Fast: received the new envelope.
    delivered = await asyncio.wait_for(fast.queue.get(), timeout=1.0)
    assert delivered.magnitude == 5.0


# ---------------------------------------------------------------------------
# publish — registry lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_on_empty_registry_is_noop() -> None:
    reg = SubscriberRegistry()
    reg.publish(_event(magnitude=5.0))  # no subscribers, no error


@pytest.mark.asyncio
async def test_unsubscribed_slot_does_not_receive_publishes() -> None:
    reg = SubscriberRegistry()
    sub = reg.subscribe(api_key_id=1, filters=[_filter(min_magnitude=4.0)])
    reg.unsubscribe(sub.id)
    reg.publish(_event(magnitude=5.0))

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.queue.get(), timeout=0.05)


# ---------------------------------------------------------------------------
# module-level singleton
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_registry_returns_same_instance(reset_registry: None) -> None:
    a = get_registry()
    b = get_registry()
    assert a is b


@pytest.mark.asyncio
async def test_reset_registry_for_tests_rebuilds_the_singleton(reset_registry: None) -> None:
    a = get_registry()
    a.subscribe(api_key_id=1, filters=[_filter(min_magnitude=4.0)])
    reset_registry_for_tests()
    b = get_registry()
    assert b is not a
    assert b.get_subscriber_count() == 0
