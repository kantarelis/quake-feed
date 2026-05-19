"""Unit tests for the ``/alerts/stream`` SSE endpoint.

Two execution modes, picked per test:

* **HTTP-layer (pre-stream gates):** plain ``await client.get(...)``
  through ``httpx.AsyncClient`` over ``ASGITransport``. These checks
  resolve before any streaming starts — the auth dep raises 401 and
  the empty-filters check raises 400 — so the response is a regular
  short body with no streaming machinery involved.
* **View-direct (live behaviour):** call
  ``AlertsStreamManagerViews.stream(request, current_key=…)`` and
  iterate ``response.body_iterator`` ourselves. The whole test runs
  inside one event loop, avoids the HTTP wire format entirely, and
  asserts on the raw ``{"event": ..., "data": ...}`` dicts the
  generator yields — much faster than waiting for
  ``aiter_lines()`` to surface a flushed frame, and immune to the
  cross-thread ``asyncio.Queue`` hazard that ``sync TestClient``
  introduces.

Per-test budget: every test completes in well under 2 seconds. The
view-direct tests publish-then-await-anext, where the queue already
holds the item by the time anext is invoked, so the 1-second
``wait_for`` upper bound is purely defensive.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from datetime import datetime, timezone
from typing import cast

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from starlette.requests import Request

from database.etls.alert_filters import AlertFiltersETL
from database.etls.api_keys import ApiKeysETL
from database.models import ApiKeyRow, EventRow
from quake.alerts.registry import get_registry, reset_registry_for_tests
from quake.api.alerts.views import AlertsStreamManagerViews
from quake.api.auth import get_vault_client, hash_key
from quake.main import Quake
from tests._auth import StubVault, issue_test_key

_NOW = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)

# ASGI scope reused across the view-direct tests.
_SCOPE: dict[str, object] = {
    "type": "http",
    "method": "GET",
    "headers": [],
    "query_string": b"",
    "path": "/alerts/stream",
}


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


@pytest.fixture(autouse=True)
def _reset_registry() -> Iterator[None]:
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


# ---------------------------------------------------------------------------
# HTTP-layer fixtures + tests — pre-stream gates only
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def authed_http() -> AsyncIterator[tuple[httpx.AsyncClient, int]]:
    """``AsyncClient`` carrying a fresh API key, plus the integer api_key_id."""
    vault = StubVault()
    quake = Quake(logger=logging.getLogger("test-alerts-stream-http"))
    quake.app.dependency_overrides[get_vault_client] = lambda: vault
    raw, headers = issue_test_key(vault=vault, scopes=[], label="streamer")
    key_row = ApiKeysETL().get_by_hash(hash_key(raw))
    assert key_row is not None

    transport = ASGITransport(app=quake.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as c:
        yield c, key_row.id


@pytest_asyncio.fixture
async def no_auth_http() -> AsyncIterator[httpx.AsyncClient]:
    vault = StubVault()
    quake = Quake(logger=logging.getLogger("test-alerts-stream-noauth"))
    quake.app.dependency_overrides[get_vault_client] = lambda: vault
    transport = ASGITransport(app=quake.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_stream_without_auth_is_401(no_auth_http: httpx.AsyncClient) -> None:
    response = await no_auth_http.get("/alerts/stream")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_stream_with_no_filters_is_400(authed_http: tuple[httpx.AsyncClient, int]) -> None:
    client, _ = authed_http
    response = await client.get("/alerts/stream")
    assert response.status_code == 400
    assert "no filters configured" in response.json()["detail"]


# ---------------------------------------------------------------------------
# View-direct helpers
# ---------------------------------------------------------------------------


_FrameGenerator = AsyncGenerator[dict[str, str], None]


async def _block_forever() -> dict[str, object]:
    """``receive`` callable that never returns — keeps ``is_disconnected`` False."""
    await asyncio.Future()
    return {"type": "http.request"}  # unreachable; satisfies the type checker


def _make_api_key_row(api_key_id: int) -> ApiKeyRow:
    """Hand-built :class:`ApiKeyRow` for the view's ``current_key`` param."""
    return ApiKeyRow(
        id=api_key_id,
        key_hash="placeholder",
        label="view-direct",
        scopes=[],
        created_at=_NOW,
        last_seen_at=None,
        revoked_at=None,
    )


@pytest_asyncio.fixture
async def view_with_filter() -> AsyncIterator[tuple[AlertsStreamManagerViews, ApiKeyRow]]:
    """Seed an api_keys row + one alert_filters row, return the view + ApiKeyRow."""
    # alert_filters has an FK to api_keys; the hash value is irrelevant
    # because the view is called directly with a hand-built ApiKeyRow.
    key_id = ApiKeysETL().insert(key_hash="placeholder-hash", label="view-direct", scopes=[])
    AlertFiltersETL().insert(key_id, min_magnitude=4.0)
    views = AlertsStreamManagerViews(logger=logging.getLogger("test-stream-view"))
    yield views, _make_api_key_row(key_id)


async def _start_and_wait_for_subscribe(body_iter: _FrameGenerator) -> asyncio.Task[dict[str, str]]:
    """Schedule the generator's first anext and let it reach its inner queue.get await.

    Returns the in-flight task so the caller can ``await`` it once a
    publish unblocks the gen, or ``cancel()`` it for cleanup. The
    single ``sleep(0)`` is enough for the loop to drive the gen
    through its synchronous subscribe + the near-immediate
    ``is_disconnected`` check, leaving it suspended on the queue.
    """
    task = asyncio.create_task(body_iter.__anext__())
    await asyncio.sleep(0)
    return task


async def _drain(task: asyncio.Task[dict[str, str]]) -> None:
    """Cancel a pending anext task and absorb the resulting exception."""
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except StopAsyncIteration:
        pass


# ---------------------------------------------------------------------------
# View-direct tests — subscription, fanout, cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_view_registers_a_subscriber_on_open(
    view_with_filter: tuple[AlertsStreamManagerViews, ApiKeyRow],
) -> None:
    views, key_row = view_with_filter
    request = Request(scope=_SCOPE, receive=_block_forever)
    response = await views.stream(request, current_key=key_row)
    body_iter = cast(_FrameGenerator, response.body_iterator)

    task = await _start_and_wait_for_subscribe(body_iter)
    try:
        assert get_registry().get_subscriber_count() == 1
    finally:
        await _drain(task)
        await body_iter.aclose()


@pytest.mark.asyncio
async def test_view_yields_alert_frame_on_matching_publish(
    view_with_filter: tuple[AlertsStreamManagerViews, ApiKeyRow],
) -> None:
    views, key_row = view_with_filter
    request = Request(scope=_SCOPE, receive=_block_forever)
    response = await views.stream(request, current_key=key_row)
    body_iter = cast(_FrameGenerator, response.body_iterator)

    task = await _start_and_wait_for_subscribe(body_iter)
    try:
        get_registry().publish(_event("ev_match", magnitude=5.0))
        frame = await asyncio.wait_for(task, timeout=1.0)
        assert frame["event"] == "alert"
        data = json.loads(frame["data"])
        assert data["event_id"] == "ev_match"
        assert data["magnitude"] == 5.0
    finally:
        await _drain(task)
        await body_iter.aclose()


@pytest.mark.asyncio
async def test_view_drops_non_matching_publish(
    view_with_filter: tuple[AlertsStreamManagerViews, ApiKeyRow],
) -> None:
    views, key_row = view_with_filter
    request = Request(scope=_SCOPE, receive=_block_forever)
    response = await views.stream(request, current_key=key_row)
    body_iter = cast(_FrameGenerator, response.body_iterator)

    task = await _start_and_wait_for_subscribe(body_iter)
    try:
        registry = get_registry()
        registry.publish(_event("ev_low", magnitude=2.0))  # filtered out (mag < 4.0)
        registry.publish(_event("ev_high", magnitude=6.0))  # delivered
        frame = await asyncio.wait_for(task, timeout=1.0)
        data = json.loads(frame["data"])
        # Only one frame arrived — the non-matching publish never reached us.
        assert data["event_id"] == "ev_high"
    finally:
        await _drain(task)
        await body_iter.aclose()


@pytest.mark.asyncio
async def test_view_unsubscribes_on_close(
    view_with_filter: tuple[AlertsStreamManagerViews, ApiKeyRow],
) -> None:
    views, key_row = view_with_filter
    request = Request(scope=_SCOPE, receive=_block_forever)
    response = await views.stream(request, current_key=key_row)
    body_iter = cast(_FrameGenerator, response.body_iterator)

    task = await _start_and_wait_for_subscribe(body_iter)
    assert get_registry().get_subscriber_count() == 1

    # Cancelling the in-flight anext propagates CancelledError into the
    # generator, which hits the finally and unsubscribes the slot. This
    # is the test's stand-in for an SSE client dropping the connection.
    await _drain(task)
    assert get_registry().get_subscriber_count() == 0
