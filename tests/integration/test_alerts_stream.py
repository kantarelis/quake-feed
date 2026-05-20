"""End-to-end smoke for the Epic-6 SSE alerts pipeline.

Wires the **entire** real path in one test:

    EventsETL.upsert_many (real INSERT)
        → quake.events_notify trigger
        → pg_notify('quake_event_inserts', row_to_json(NEW))
        → AlertListener (real async LISTEN connection, started by the lifespan)
        → SubscriberRegistry.publish + FilterMatcher
        → EventSourceResponse generator
        → SSE client over a real TCP socket

The unit tests (``test_alert_listener.py``, ``test_subscriber_registry.py``,
``test_alerts_stream_api.py``) already cover each leg in isolation; this
test's unique job is to prove they compose through the *real wire format*
and the *lifespan-started* listener.

Why a real uvicorn server instead of ``httpx.ASGITransport``
------------------------------------------------------------
``ASGITransport.handle_async_request`` (httpx 0.28) runs ``await
app(scope, receive, send)`` **to completion** and buffers every body
chunk before returning a response. An ``EventSourceResponse`` never
completes — the generator loops until the client disconnects — so
streaming it over ``ASGITransport`` would hang forever (the same failure
the Task-6 unit tests hit with ``TestClient.stream``). The only way to
exercise true incremental SSE delivery with ``httpx.AsyncClient.stream``
is over a real TCP listener, so we run ``uvicorn`` on an ephemeral port
in a background thread. Running it in a thread (rather than as a task in
the test's own loop) also keeps every ``asyncio.Queue`` — the listener,
the registry, and the SSE generator — bound to a single loop (uvicorn's),
sidestepping the cross-loop queue hazard entirely.

``lifespan="on"`` makes uvicorn run ``Quake._lifespan``, which starts the
real ``AlertListener`` task. We don't get a handle to that listener's
``ready`` event from out here, so two readiness gates make the test
deterministic instead of racy:

* **Listener ready** — poll ``pg_stat_activity`` until the listener's
  ``LISTEN quake_event_inserts`` connection shows up. A NOTIFY fired
  before the listener is listening would be lost (pg_notify is
  fire-and-forget), so we must not INSERT until it's connected.
* **Subscriber ready** — poll the process-wide ``SubscriberRegistry``
  (shared by the in-thread server and this test) until the SSE
  generator has registered its slot. Publishing before the slot exists
  would drop the envelope on the floor.

The registry singleton is reset *before* the server boots so the
lifespan's listener and the SSE view resolve the same fresh instance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
import pytest_asyncio
import uvicorn

from database.etls.endpoint_locks import EndpointLocksETL
from database.etls.events import EventsETL
from database.main import transaction
from database.models import EventRow
from quake.alerts.registry import get_registry, reset_registry_for_tests
from quake.api.auth import get_vault_client
from quake.main import Quake
from tests._auth import StubVault, issue_test_key

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Listener's LISTEN statement, verbatim — this is exactly what shows up in
# pg_stat_activity.query for the listener's autocommit connection.
_LISTEN_QUERY = "LISTEN quake_event_inserts"

# Mirrors the truncate set the other integration tests use, plus
# alert_filters (this epic's table) and an explicit INGESTION_LOCK clear.
_TRUNCATE_SQL = """
    TRUNCATE
        quake.events,
        quake.event_revisions,
        quake.alert_filters,
        quake.api_keys,
        quake.ingestion_runs
    RESTART IDENTITY CASCADE
"""

# Absolute anchor so the seed events are deterministic. ev_match and ev_low
# share this time but differ on event_id — the upsert conflict key is
# (event_id, time), so both take the INSERT path and both fire the trigger.
_NOW = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)


def _event(event_id: str, *, magnitude: float) -> EventRow:
    return EventRow(
        event_id=event_id,
        time=_NOW,
        magnitude=magnitude,
        magnitude_type="md",
        depth_km=10.0,
        latitude=37.0,
        longitude=23.0,
        place="integration-land",
        status="reviewed",
        tsunami=False,
        url=f"https://earthquake.usgs.gov/earthquakes/eventpage/{event_id}",
        inserted_at=_NOW,
        updated_at=_NOW,
    )


async def _wait_until(predicate: Callable[[], bool], *, timeout: float, what: str) -> None:
    """Poll ``predicate`` until it's true or ``timeout`` elapses."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


def _listener_is_connected() -> bool:
    """True once the AlertListener's LISTEN connection is visible in Postgres."""
    with transaction() as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_stat_activity WHERE query = %s LIMIT 1",
            (_LISTEN_QUERY,),
        ).fetchone()
    return row is not None


async def _read_alert(line_iter: AsyncIterator[str], *, timeout: float) -> dict[str, Any]:
    """Read SSE lines until one ``event: alert`` frame's ``data:`` arrives.

    Raises ``TimeoutError`` if no alert frame surfaces within ``timeout`` —
    which the no-delivery assertion relies on. Non-alert lines (keep-alive
    ping comments, frame-boundary blanks) are skipped.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    current_event: str | None = None
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError("no alert frame within timeout")
        line = (await asyncio.wait_for(line_iter.__anext__(), timeout=remaining)).strip()
        if not line:
            current_event = None
        elif line.startswith("event:"):
            current_event = line[len("event:") :].strip()
        elif line.startswith("data:") and current_event == "alert":
            return json.loads(line[len("data:") :].strip())


@pytest_asyncio.fixture
async def live_alerts_server() -> AsyncIterator[tuple[int, dict[str, str]]]:
    """Boot the real Quake app under uvicorn with the lifespan listener live.

    Yields ``(port, auth_headers)``. The DB is truncated and one API key
    is issued *before* the server starts; the registry is reset so the
    lifespan's listener and the SSE view share one fresh instance.
    """
    with transaction() as conn:
        conn.execute(_TRUNCATE_SQL)
    EndpointLocksETL().clear_lock("INGESTION_LOCK")
    reset_registry_for_tests()

    vault = StubVault()
    quake = Quake(logger=logging.getLogger("test-alerts-stream-integration"))
    quake.app.dependency_overrides[get_vault_client] = lambda: vault
    _, headers = issue_test_key(vault=vault, scopes=[], label="streamer")

    config = uvicorn.Config(quake.app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn-alerts-it", daemon=True)
    thread.start()
    try:
        await _wait_until(lambda: server.started and bool(server.servers), timeout=10.0, what="uvicorn startup")
        port = int(server.servers[0].sockets[0].getsockname()[1])
        await _wait_until(_listener_is_connected, timeout=10.0, what="AlertListener LISTEN")
        yield port, headers
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 10.0)
        reset_registry_for_tests()


async def test_sse_delivers_matching_and_drops_non_matching(
    live_alerts_server: tuple[int, dict[str, str]],
) -> None:
    """One pass: a matching event reaches the SSE client; a sub-threshold one doesn't."""
    port, headers = live_alerts_server
    base_url = f"http://127.0.0.1:{port}"

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=httpx.Timeout(10.0)) as client:
        # Register a single filter: magnitude >= 4.0 (no geo constraint).
        response = await client.post("/alerts/filters", json={"min_magnitude": 4.0})
        assert response.status_code == 201, response.text

        async with client.stream("GET", "/alerts/stream") as stream:
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            lines = stream.aiter_lines()

            # The generator subscribes to the shared registry on its first
            # iteration; wait for the slot before publishing anything.
            await _wait_until(
                lambda: get_registry().get_subscriber_count() == 1,
                timeout=5.0,
                what="SSE subscriber registration",
            )

            # Matching event — exercises the full trigger → NOTIFY → listener
            # → registry → SSE path.
            EventsETL().upsert_many([_event("ev_match", magnitude=5.0)])
            data = await _read_alert(lines, timeout=5.0)
            assert data["event_id"] == "ev_match"
            assert data["magnitude"] == 5.0
            assert data["place"] == "integration-land"

            # Non-matching event (below the 4.0 floor) — the matcher must drop
            # it, so no further frame arrives in the wait window.
            EventsETL().upsert_many([_event("ev_low", magnitude=1.0)])
            with pytest.raises(TimeoutError):
                await _read_alert(lines, timeout=1.0)
