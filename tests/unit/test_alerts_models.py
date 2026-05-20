"""Unit tests for :mod:`models.alerts`.

Three model surfaces are exercised:

* :class:`AlertFilter` — the request DTO with the bbox-XOR-center+radius
  shape validator. Most assertions live here.
* :class:`AlertFilterResponse` — DB-row → public-response round-trip.
* :class:`AlertEnvelope` — ``model_validate`` against a row-shaped dict
  (the path the listener will use in Task 4).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from database.models import AlertFilterRow, EventRow
from models.alerts import AlertEnvelope, AlertFilter, AlertFilterResponse

# ---------------------------------------------------------------------------
# AlertFilter — happy paths
# ---------------------------------------------------------------------------


def test_filter_min_magnitude_only_is_valid() -> None:
    f = AlertFilter(min_magnitude=4.0)
    assert f.min_magnitude == 4.0
    assert f.bbox_min_lat is None
    assert f.center_lat is None


def test_filter_bbox_only_is_valid() -> None:
    f = AlertFilter(
        bbox_min_lat=10.0,
        bbox_min_lon=20.0,
        bbox_max_lat=11.0,
        bbox_max_lon=21.0,
    )
    assert f.bbox_min_lat == 10.0
    assert f.center_lat is None


def test_filter_center_radius_only_is_valid() -> None:
    f = AlertFilter(center_lat=37.0, center_lon=23.0, radius_km=100.0)
    assert f.radius_km == 100.0
    assert f.bbox_min_lat is None


def test_filter_bbox_with_min_magnitude_is_valid() -> None:
    f = AlertFilter(
        min_magnitude=3.0,
        bbox_min_lat=10.0,
        bbox_min_lon=20.0,
        bbox_max_lat=11.0,
        bbox_max_lon=21.0,
    )
    assert f.min_magnitude == 3.0
    assert f.bbox_min_lat == 10.0


def test_filter_center_radius_with_min_magnitude_is_valid() -> None:
    f = AlertFilter(min_magnitude=2.5, center_lat=37.0, center_lon=23.0, radius_km=50.0)
    assert f.min_magnitude == 2.5
    assert f.radius_km == 50.0


# ---------------------------------------------------------------------------
# AlertFilter — shape errors
# ---------------------------------------------------------------------------


def test_filter_empty_payload_is_rejected() -> None:
    with pytest.raises(ValidationError, match="empty filter"):
        AlertFilter()


def test_filter_bbox_and_center_together_is_rejected() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        AlertFilter(
            bbox_min_lat=10.0,
            bbox_min_lon=20.0,
            bbox_max_lat=11.0,
            bbox_max_lon=21.0,
            center_lat=37.0,
            center_lon=23.0,
            radius_km=100.0,
        )


def test_filter_partial_bbox_is_rejected() -> None:
    with pytest.raises(ValidationError, match="bbox requires all of"):
        AlertFilter(bbox_min_lat=10.0, bbox_min_lon=20.0, bbox_max_lat=11.0)


def test_filter_partial_center_is_rejected() -> None:
    with pytest.raises(ValidationError, match="center\\+radius requires all of"):
        AlertFilter(center_lat=37.0, center_lon=23.0)


def test_filter_inverted_bbox_lat_is_rejected() -> None:
    with pytest.raises(ValidationError, match="bbox_min_lat must be <= bbox_max_lat"):
        AlertFilter(
            bbox_min_lat=15.0,
            bbox_min_lon=20.0,
            bbox_max_lat=10.0,
            bbox_max_lon=21.0,
        )


def test_filter_inverted_bbox_lon_is_rejected() -> None:
    with pytest.raises(ValidationError, match="bbox_min_lon must be <= bbox_max_lon"):
        AlertFilter(
            bbox_min_lat=10.0,
            bbox_min_lon=25.0,
            bbox_max_lat=11.0,
            bbox_max_lon=20.0,
        )


# ---------------------------------------------------------------------------
# AlertFilter — per-field range errors
# ---------------------------------------------------------------------------


def test_filter_magnitude_below_floor_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AlertFilter(min_magnitude=-2.0)


def test_filter_zero_radius_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AlertFilter(center_lat=37.0, center_lon=23.0, radius_km=0.0)


def test_filter_negative_radius_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AlertFilter(center_lat=37.0, center_lon=23.0, radius_km=-10.0)


def test_filter_out_of_range_lat_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AlertFilter(
            bbox_min_lat=-100.0,
            bbox_min_lon=0.0,
            bbox_max_lat=10.0,
            bbox_max_lon=10.0,
        )


def test_filter_out_of_range_lon_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AlertFilter(center_lat=0.0, center_lon=200.0, radius_km=10.0)


def test_filter_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AlertFilter.model_validate({"min_magnitude": 3.0, "rogue": 1})


# ---------------------------------------------------------------------------
# AlertFilterResponse — DB row round-trip
# ---------------------------------------------------------------------------


def test_filter_response_consumes_db_row() -> None:
    row = AlertFilterRow(
        id=7,
        api_key_id=42,
        min_magnitude=4.5,
        bbox_min_lat=None,
        bbox_min_lon=None,
        bbox_max_lat=None,
        bbox_max_lon=None,
        center_lat=37.0,
        center_lon=23.0,
        radius_km=100.0,
        created_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )
    response = AlertFilterResponse.model_validate(row)
    assert response.id == 7
    assert response.api_key_id == 42
    assert response.min_magnitude == 4.5
    assert response.radius_km == 100.0
    assert response.bbox_min_lat is None


# ---------------------------------------------------------------------------
# AlertEnvelope — round-trip from EventRow and from a row-shaped dict
# ---------------------------------------------------------------------------


def test_envelope_consumes_event_row() -> None:
    now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    row = EventRow(
        event_id="us6000abcd",
        time=now,
        magnitude=5.7,
        magnitude_type="mb",
        depth_km=10.5,
        latitude=37.0,
        longitude=23.0,
        place="near somewhere",
        status="reviewed",
        tsunami=False,
        url="https://earthquake.usgs.gov/earthquakes/eventpage/us6000abcd",
        inserted_at=now,
        updated_at=now,
    )
    envelope = AlertEnvelope.model_validate(row)
    assert envelope.event_id == "us6000abcd"
    assert envelope.magnitude == 5.7
    assert envelope.place == "near somewhere"
    assert envelope.url is not None


def test_envelope_consumes_row_shaped_dict() -> None:
    """The pg_notify path hands the listener a dict from ``row_to_json``."""
    now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    payload = {
        "event_id": "nc12345",
        "time": now,
        "magnitude": 3.2,
        "magnitude_type": "md",
        "depth_km": 4.0,
        "latitude": 38.0,
        "longitude": -122.0,
        "place": "California",
        "url": "https://example.test/nc12345",
        # extra keys from row_to_json — should be ignored, not rejected.
        "inserted_at": now,
        "updated_at": now,
        "tsunami": False,
        "status": "automatic",
    }
    envelope = AlertEnvelope.model_validate(payload)
    assert envelope.event_id == "nc12345"
    assert envelope.depth_km == 4.0


def test_envelope_round_trips_through_json() -> None:
    now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    original = AlertEnvelope(
        event_id="us6000abcd",
        time=now,
        magnitude=5.7,
        magnitude_type="mb",
        depth_km=10.5,
        latitude=37.0,
        longitude=23.0,
        place="near somewhere",
        url="https://example.test/us6000abcd",
    )
    json_blob = original.model_dump_json()
    restored = AlertEnvelope.model_validate_json(json_blob)
    assert restored == original
