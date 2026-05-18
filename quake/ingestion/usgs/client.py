"""HTTP client for the USGS realtime earthquake feed.

Wraps ``httpx.Client`` with tenacity-driven retries on transport-level
failures (connection errors, timeouts, transient 5xx). 4xx responses are
not retried — they signal a bad request shape that no amount of
retrying will fix.

Usage::

    with UsgsClient() as client:
        raw = client.fetch(UsgsFeed.ALL_HOUR)

The returned ``dict`` is the parsed JSON of a USGS FeatureCollection.
Mapping into :class:`database.models.EventRow` is the parser's job (next
task).
"""

from __future__ import annotations

from enum import StrEnum
from types import TracebackType
from typing import Any, Self

import httpx
import tenacity


class UsgsFeed(StrEnum):
    """USGS realtime feed URLs.

    Only ``ALL_HOUR`` is wired in for now — it's the lowest-latency tier
    (60-minute window refreshed every 60 seconds), matching our poll
    cadence. Adding day/week tiers is a one-line addition when needed.
    """

    ALL_HOUR = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"


class UsgsClientError(RuntimeError):
    """Raised for non-retryable USGS failures (4xx) or after final retry."""


# Retryable transport-layer failures. 4xx errors are deliberately excluded —
# they indicate a bad request shape, not a transient condition.
_RETRYABLE = (httpx.TransportError, httpx.TimeoutException)


class UsgsClient:
    """Synchronous HTTP client for the USGS realtime feed."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._client = httpx.Client(timeout=timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
        retry=tenacity.retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    def _get(self, url: str) -> httpx.Response:
        return self._client.get(url)

    def fetch(self, feed: UsgsFeed) -> dict[str, Any]:
        """GET ``feed`` and return its parsed JSON body.

        Retries (up to 3 attempts, 1s→10s exponential backoff) on transport
        errors and timeouts. A non-2xx response status raises
        :class:`UsgsClientError` without retrying — those are typically 4xx
        bugs in the request, not transient. A transport failure that
        survives all retries is also surfaced as :class:`UsgsClientError`,
        with the underlying httpx exception chained via ``__cause__``.
        """
        try:
            response = self._get(str(feed))
        except _RETRYABLE as exc:
            raise UsgsClientError(f"USGS unreachable for {feed} after retries: {exc}") from exc
        if response.status_code >= 400:
            raise UsgsClientError(f"USGS returned HTTP {response.status_code} for {feed}")
        try:
            data = response.json()
        except ValueError as exc:
            raise UsgsClientError(f"USGS response was not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise UsgsClientError(f"USGS response was not a JSON object (got {type(data).__name__})")
        return data
