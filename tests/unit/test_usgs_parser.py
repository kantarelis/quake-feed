"""Unit tests for :func:`quake.ingestion.usgs.parser.parse_feed`.

Driven by a captured USGS response in ``tests/fixtures/usgs_all_hour.json``
so tests stay offline and deterministic. The captured fixture has 6
features; spot-checks pin a known event's round-trip fields.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from database.models import EventRow
from quake.ingestion.usgs.parser import parse_feed

_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "usgs_all_hour.json"


@pytest.fixture
def feed() -> dict[str, Any]:
    return json.loads(_FIXTURE_PATH.read_text())


def test_parses_every_feature_in_fixture(feed: dict[str, Any]) -> None:
    rows = parse_feed(feed)
    assert len(rows) == len(feed["features"])
    assert all(isinstance(r, EventRow) for r in rows)


def test_round_trips_known_event(feed: dict[str, Any]) -> None:
    """Spot-check the first feature against its raw USGS values."""
    raw = feed["features"][0]
    rows = parse_feed(feed)
    row = next(r for r in rows if r.event_id == raw["id"])

    assert row.magnitude == raw["properties"]["mag"]
    assert row.magnitude_type == raw["properties"]["magType"]
    assert row.place == raw["properties"]["place"]
    assert row.status == raw["properties"]["status"]
    assert row.url == raw["properties"]["url"]
    # USGS coordinates are [lon, lat, depth_km]
    assert row.longitude == raw["geometry"]["coordinates"][0]
    assert row.latitude == raw["geometry"]["coordinates"][1]
    assert row.depth_km == raw["geometry"]["coordinates"][2]
    # USGS time is ms since epoch UTC → datetime
    expected = datetime.fromtimestamp(raw["properties"]["time"] / 1000, tz=timezone.utc)
    assert row.time == expected
    # tsunami is int 0/1 in USGS → bool in our schema
    assert row.tsunami is bool(raw["properties"]["tsunami"])


def test_skips_feature_missing_magnitude_and_keeps_the_rest(
    feed: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A feature without properties.mag is dropped + logged; siblings unaffected.

    ``setup_logger`` sets ``propagate=False`` so the JSON handler is the
    sole sink in production. caplog attaches at the root logger, so we
    re-enable propagation just for this test to capture the warning.
    """
    monkeypatch.setattr(logging.getLogger("usgs-parser"), "propagate", True)
    corrupted = copy.deepcopy(feed)
    corrupted["features"][0]["properties"].pop("mag")
    expected_count = len(feed["features"]) - 1

    with caplog.at_level(logging.WARNING, logger="usgs-parser"):
        rows = parse_feed(corrupted)

    assert len(rows) == expected_count
    # the dropped feature's id is not in the result
    dropped_id = feed["features"][0]["id"]
    assert all(r.event_id != dropped_id for r in rows)
    # warning emitted
    assert any("malformed" in rec.message.lower() for rec in caplog.records)


def test_skips_feature_missing_coordinates(feed: dict[str, Any]) -> None:
    corrupted = copy.deepcopy(feed)
    corrupted["features"][0]["geometry"]["coordinates"] = []
    rows = parse_feed(corrupted)
    assert len(rows) == len(feed["features"]) - 1


def test_handles_empty_feature_collection() -> None:
    rows = parse_feed({"type": "FeatureCollection", "features": []})
    assert rows == []


def test_handles_missing_features_key() -> None:
    """A dict with no 'features' key returns an empty list (defensive)."""
    rows = parse_feed({"type": "FeatureCollection"})
    assert rows == []


def test_handles_missing_optional_depth(feed: dict[str, Any]) -> None:
    """A 2-element coordinates array (lat/lon only) parses with depth_km = None."""
    corrupted = copy.deepcopy(feed)
    corrupted["features"][0]["geometry"]["coordinates"] = corrupted["features"][0]["geometry"]["coordinates"][:2]
    rows = parse_feed(corrupted)
    row = next(r for r in rows if r.event_id == feed["features"][0]["id"])
    assert row.depth_km is None
