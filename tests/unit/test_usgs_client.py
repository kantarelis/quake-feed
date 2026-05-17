"""Unit tests for :class:`quake.ingestion.usgs.client.UsgsClient`.

Uses ``respx`` to intercept httpx requests so tests stay offline and
deterministic. The retry-wait fixture below patches tenacity's
exponential backoff to zero so a 3-attempt sequence finishes in
milliseconds instead of ~3s.
"""

from __future__ import annotations

import httpx
import pytest
import respx
import tenacity

from quake.ingestion.usgs.client import UsgsClient, UsgsClientError, UsgsFeed

_URL = str(UsgsFeed.ALL_HOUR)


@pytest.fixture(autouse=True)
def _no_wait_between_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass tenacity's exponential backoff for the duration of each test.

    ``getattr`` here defeats mypy's view of the decorated method — tenacity
    attaches the ``Retrying`` instance as ``.retry`` at runtime but the type
    stubs don't carry it.
    """
    retrying = getattr(UsgsClient._get, "retry")
    monkeypatch.setattr(retrying, "wait", tenacity.wait_none())


@respx.mock
def test_fetch_happy_path_returns_parsed_json() -> None:
    payload = {"type": "FeatureCollection", "features": []}
    route = respx.get(_URL).mock(return_value=httpx.Response(200, json=payload))

    with UsgsClient() as client:
        data = client.fetch(UsgsFeed.ALL_HOUR)

    assert data == payload
    assert route.call_count == 1


@respx.mock
def test_fetch_retries_transport_error_then_succeeds() -> None:
    """Two transient ConnectErrors then a 200 → returns the success body."""
    route = respx.get(_URL).mock(
        side_effect=[
            httpx.ConnectError("transient 1"),
            httpx.ConnectError("transient 2"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    with UsgsClient() as client:
        data = client.fetch(UsgsFeed.ALL_HOUR)

    assert data == {"ok": True}
    assert route.call_count == 3


@respx.mock
def test_fetch_exhausts_retries_then_raises_usgs_client_error() -> None:
    """A persistently-failing connection raises UsgsClientError after 3 attempts."""
    route = respx.get(_URL).mock(side_effect=httpx.ConnectError("permanent"))

    with UsgsClient() as client:
        with pytest.raises(UsgsClientError, match="unreachable"):
            client.fetch(UsgsFeed.ALL_HOUR)

    assert route.call_count == 3


@respx.mock
def test_fetch_http_4xx_raises_without_retry() -> None:
    """A 400 response surfaces as UsgsClientError and is NOT retried."""
    route = respx.get(_URL).mock(return_value=httpx.Response(400, json={"error": "bad"}))

    with UsgsClient() as client:
        with pytest.raises(UsgsClientError, match="400"):
            client.fetch(UsgsFeed.ALL_HOUR)

    assert route.call_count == 1
