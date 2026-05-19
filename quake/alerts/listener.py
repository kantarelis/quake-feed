"""Async Postgres ``LISTEN`` task that feeds :class:`SubscriberRegistry`.

The migration in ``20260519154655_events_notify.sql`` installs a trigger
that fires ``pg_notify('quake_event_inserts', row_to_json(NEW))`` on every
INSERT into ``quake.events``. The Celery worker writes those rows; the
API process owns this listener, which decodes each notification and
hands the event to the in-process :class:`SubscriberRegistry`.

Lifecycle:

* :meth:`AlertListener.run` is started as an ``asyncio.create_task`` by
  the FastAPI lifespan (``quake.main.Quake``) on app startup.
* On shutdown, the lifespan calls :meth:`AlertListener.stop` and awaits
  the task — clean cancellation, no leaked connections.
* The supervisor loop reopens the connection with exponential backoff
  if the inner ``async for`` exits for any reason other than a stop
  request (1s → 30s cap). Cancellation breaks out cleanly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import psycopg

from database.models import EventRow
from functions.environment import get_environmental_variables
from quake.alerts.registry import SubscriberRegistry

_CHANNEL = "quake_event_inserts"
_BACKOFF_INITIAL_S = 1.0
_BACKOFF_MAX_S = 30.0

logger = logging.getLogger("AlertListener")


class AlertListener:
    """Long-lived ``LISTEN`` connection that bridges Postgres NOTIFY → in-process bus.

    Owns one :class:`psycopg.AsyncConnection` opened in autocommit mode
    (``LISTEN`` is meaningless inside a transaction in psycopg's
    default mode). Constructed by the lifespan; the registry is
    injected so tests can pass a fresh one.
    """

    def __init__(self, registry: SubscriberRegistry) -> None:
        self._registry = registry
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._conn: psycopg.AsyncConnection[Any] | None = None

    @property
    def ready(self) -> asyncio.Event:
        """Set once the LISTEN has been issued on a live connection.

        Tests ``await listener.ready.wait()`` before issuing the work
        that should trigger NOTIFY, so the test doesn't race the
        listener's connection setup.
        """
        return self._ready

    async def run(self) -> None:
        """Supervisor: connect → LISTEN → loop, reconnect on failure with backoff."""
        backoff = _BACKOFF_INITIAL_S
        while not self._stop.is_set():
            try:
                await self._listen_once()
                # Inner loop exited without raising — either we were told to
                # stop (loop will exit via the while-guard) or the connection
                # closed cleanly. Reset backoff so the next iteration is prompt.
                backoff = _BACKOFF_INITIAL_S
            except asyncio.CancelledError:
                logger.info("AlertListener cancelled — exiting")
                break
            except Exception as exc:
                logger.warning(
                    "AlertListener connection error; retrying",
                    extra={"error": str(exc), "backoff_seconds": backoff},
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    break  # stop requested during backoff
                except asyncio.TimeoutError:
                    pass  # backoff elapsed, retry
                backoff = min(backoff * 2, _BACKOFF_MAX_S)

        await self._close_connection()
        logger.info("AlertListener stopped")

    def stop(self) -> None:
        """Request a clean shutdown. The supervisor exits on next loop check."""
        self._stop.set()

    async def _listen_once(self) -> None:
        """Open one connection, LISTEN, consume notifications until stopped or broken.

        The inner ``conn.notifies(timeout=1.0)`` generator returns at the
        latest after one second if no NOTIFY arrives — that's how the
        outer loop notices :meth:`stop` and exits cleanly without
        hanging on a dormant channel.
        """
        conninfo = self._build_conninfo()
        async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
            self._conn = conn
            await conn.execute(f"LISTEN {_CHANNEL}")
            self._ready.set()
            logger.info("AlertListener connected", extra={"channel": _CHANNEL})
            while not self._stop.is_set():
                async for notify in conn.notifies(timeout=1.0):
                    if self._stop.is_set():
                        break
                    self._handle_notify(notify.payload)

    def _handle_notify(self, payload: str) -> None:
        """Decode one NOTIFY payload and publish through the registry.

        Malformed JSON or shape errors are logged and swallowed — a bad
        notification must not take down the listener task. The trigger
        in the migration emits a fixed row_to_json shape, so anything
        else on the channel is either operator noise or a future
        protocol bump we'll handle then.
        """
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            logger.warning(
                "skipping malformed NOTIFY payload (not JSON)",
                extra={"error": str(exc), "payload_prefix": payload[:80]},
            )
            return

        try:
            event = EventRow.model_validate(data)
        except Exception as exc:
            logger.warning(
                "skipping NOTIFY payload (not an events row)",
                extra={"error": str(exc)},
            )
            return

        self._registry.publish(event)

    async def _close_connection(self) -> None:
        if self._conn is not None and not self._conn.closed:
            try:
                await self._conn.close()
            except Exception as exc:
                logger.warning("error closing listener connection", extra={"error": str(exc)})
        self._conn = None

    @staticmethod
    def _build_conninfo() -> str:
        cfg = get_environmental_variables().database
        return f"host={cfg.host} port={cfg.port} user={cfg.username} password={cfg.password} dbname={cfg.name}"
