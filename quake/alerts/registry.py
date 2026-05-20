"""In-process pub/sub for SSE alert subscribers.

Each SSE connection holds one :class:`Subscriber` slot in a process-wide
:class:`SubscriberRegistry`. A slot owns:

* the snapshot of the connection's filters (taken at connect time —
  mid-stream filter edits require the client to reconnect, per
  ``PLAN.md`` design choice 6),
* a bounded :class:`asyncio.Queue` the SSE view reads from.

:meth:`SubscriberRegistry.publish` is the single entry point for events
coming off the Postgres ``LISTEN`` channel (Task 4). It walks every
slot, runs :func:`quake.alerts.matcher.matches` against each filter in
the snapshot (OR across the snapshot — see design choice 3), and pushes
the envelope into the queue of every slot that matches.

Back-pressure: queues are bounded (default ``maxsize=100``). If a
subscriber's queue is full when an envelope is ready, the envelope is
**dropped for that slot only** with a warning log. Slow subscribers
don't get to stall the fanout for everyone else — live alerts beat
dead alerts.

The singleton (``_REGISTRY`` + :func:`get_registry`) is intentional —
the registry is a per-process bus like ``prometheus_client``'s default
registry. Tests reset it via the ``reset_registry`` fixture in
``tests/unit/test_subscriber_registry.py``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from itertools import count

from database.models import AlertFilterRow, EventRow
from models.alerts import AlertEnvelope
from quake.alerts.matcher import matches

_DEFAULT_QUEUE_MAXSIZE = 100

logger = logging.getLogger("SubscriberRegistry")


@dataclass
class Subscriber:
    """One connected SSE client.

    ``filters`` is the snapshot taken at subscribe time; the registry
    never mutates it. ``queue`` is an unbounded-from-the-consumer's
    perspective channel — the SSE view reads it with ``await queue.get()``.
    """

    id: int
    api_key_id: int
    filters: list[AlertFilterRow]
    queue: asyncio.Queue[AlertEnvelope] = field(repr=False)


class SubscriberRegistry:
    """In-process fanout: subscribe / unsubscribe / publish."""

    def __init__(self, *, queue_maxsize: int = _DEFAULT_QUEUE_MAXSIZE) -> None:
        self._subs: dict[int, Subscriber] = {}
        self._ids = count(start=1)
        self._queue_maxsize = queue_maxsize

    def subscribe(self, api_key_id: int, filters: list[AlertFilterRow]) -> Subscriber:
        """Register a new subscriber and return the slot.

        ``filters`` is stored by reference — the caller is expected to
        hand over a fresh snapshot list rather than the live ETL result
        (the ETL call site does this already; documented for clarity).
        """
        sub_id = next(self._ids)
        subscriber = Subscriber(
            id=sub_id,
            api_key_id=api_key_id,
            filters=filters,
            queue=asyncio.Queue(maxsize=self._queue_maxsize),
        )
        self._subs[sub_id] = subscriber
        logger.info(
            "subscriber registered",
            extra={"sub_id": sub_id, "api_key_id": api_key_id, "filter_count": len(filters)},
        )
        return subscriber

    def unsubscribe(self, sub_id: int) -> None:
        """Remove a slot. Idempotent on unknown ids."""
        sub = self._subs.pop(sub_id, None)
        if sub is not None:
            logger.info(
                "subscriber removed",
                extra={"sub_id": sub_id, "api_key_id": sub.api_key_id},
            )

    def publish(self, event: EventRow) -> None:
        """Fan an event out to every subscriber whose filter matches.

        OR across a subscriber's filters: a slot receives the envelope
        if *any* of its filters match. Slots with empty filter lists are
        skipped — an empty snapshot can't match anything we'd want to
        send (and the API layer rejects empty-filter subscriptions in
        Task 6 anyway).
        """
        envelope: AlertEnvelope | None = None  # build lazily; no subs → no work
        for sub in self._subs.values():
            if not sub.filters:
                continue
            if not any(matches(f, event) for f in sub.filters):
                continue
            if envelope is None:
                envelope = AlertEnvelope.model_validate(event)
            try:
                sub.queue.put_nowait(envelope)
            except asyncio.QueueFull:
                logger.warning(
                    "subscriber queue full — dropping envelope",
                    extra={
                        "sub_id": sub.id,
                        "api_key_id": sub.api_key_id,
                        "event_id": event.event_id,
                    },
                )

    def get_subscriber_count(self) -> int:
        """Number of currently-registered subscribers (for tests + observability)."""
        return len(self._subs)


_REGISTRY: SubscriberRegistry | None = None


def get_registry() -> SubscriberRegistry:
    """Return the process-wide registry, creating it on first access."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = SubscriberRegistry()
    return _REGISTRY


def reset_registry_for_tests() -> None:
    """Drop the module-level singleton so the next ``get_registry`` call rebuilds it.

    Test-only hook. Not called by production code. Lives here (rather
    than under tests/) so production imports don't need a sibling import.
    """
    global _REGISTRY
    _REGISTRY = None
