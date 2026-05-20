"""Unit tests for :func:`quake.alerts.matcher.matches`.

Exercises every predicate (magnitude / bbox / center+radius) in
isolation and in combination, against a fresh :class:`EventRow` /
:class:`AlertFilterRow` per case. No DB, no async — the matcher is
pure.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from database.models import AlertFilterRow, EventRow
from quake.alerts.matcher import matches

_NOW = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


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


def _filter(
    *,
    min_magnitude: float | None = None,
    bbox_min_lat: float | None = None,
    bbox_min_lon: float | None = None,
    bbox_max_lat: float | None = None,
    bbox_max_lon: float | None = None,
    center_lat: float | None = None,
    center_lon: float | None = None,
    radius_km: float | None = None,
) -> AlertFilterRow:
    return AlertFilterRow(
        id=1,
        api_key_id=1,
        min_magnitude=min_magnitude,
        bbox_min_lat=bbox_min_lat,
        bbox_min_lon=bbox_min_lon,
        bbox_max_lat=bbox_max_lat,
        bbox_max_lon=bbox_max_lon,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_km=radius_km,
        created_at=_NOW,
        updated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# magnitude predicate
# ---------------------------------------------------------------------------


def test_magnitude_above_threshold_passes() -> None:
    assert matches(_filter(min_magnitude=4.0), _event(magnitude=5.0))


def test_magnitude_below_threshold_fails() -> None:
    assert not matches(_filter(min_magnitude=4.0), _event(magnitude=3.5))


def test_magnitude_equal_threshold_passes() -> None:
    """Boundary is inclusive: event.magnitude == filter.min_magnitude is a match."""
    assert matches(_filter(min_magnitude=4.0), _event(magnitude=4.0))


# ---------------------------------------------------------------------------
# bbox predicate
# ---------------------------------------------------------------------------

# A simple square around (37.0, 23.0): lat in [36, 38], lon in [22, 24].
_BBOX_KWARGS = dict(
    bbox_min_lat=36.0,
    bbox_min_lon=22.0,
    bbox_max_lat=38.0,
    bbox_max_lon=24.0,
)


def test_bbox_inside_passes() -> None:
    assert matches(_filter(**_BBOX_KWARGS), _event(latitude=37.0, longitude=23.0))


def test_bbox_outside_lat_fails() -> None:
    assert not matches(_filter(**_BBOX_KWARGS), _event(latitude=40.0, longitude=23.0))


def test_bbox_outside_lon_fails() -> None:
    assert not matches(_filter(**_BBOX_KWARGS), _event(latitude=37.0, longitude=30.0))


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (36.0, 23.0),  # south edge
        (38.0, 23.0),  # north edge
        (37.0, 22.0),  # west edge
        (37.0, 24.0),  # east edge
        (36.0, 22.0),  # SW corner
        (38.0, 24.0),  # NE corner
    ],
)
def test_bbox_on_edge_is_inclusive(lat: float, lon: float) -> None:
    assert matches(_filter(**_BBOX_KWARGS), _event(latitude=lat, longitude=lon))


# ---------------------------------------------------------------------------
# center + radius predicate
# ---------------------------------------------------------------------------

# Center on (37.0, 23.0), 100 km radius.
_CENTER_KWARGS = dict(center_lat=37.0, center_lon=23.0, radius_km=100.0)


def test_center_radius_inside_passes() -> None:
    # ~11 km north of the centre — well inside 100 km.
    assert matches(_filter(**_CENTER_KWARGS), _event(latitude=37.1, longitude=23.0))


def test_center_radius_at_center_passes() -> None:
    assert matches(_filter(**_CENTER_KWARGS), _event(latitude=37.0, longitude=23.0))


def test_center_radius_outside_fails() -> None:
    # ~333 km north of the centre (3.0° latitude ≈ 333 km).
    assert not matches(_filter(**_CENTER_KWARGS), _event(latitude=40.0, longitude=23.0))


def test_center_radius_just_outside_fails() -> None:
    # ~133 km north of the centre — outside the 100 km radius.
    assert not matches(_filter(**_CENTER_KWARGS), _event(latitude=38.2, longitude=23.0))


# Note on antimeridian coverage: bbox spanning ±180 longitude (e.g.
# bbox_min_lon=170, bbox_max_lon=-170) is rejected at the API layer
# by the AlertFilter validator (bbox_min_lon must be <= bbox_max_lon).
# The matcher therefore assumes ordered bounds; the no-antimeridian
# case is locked at the API boundary.


# ---------------------------------------------------------------------------
# combinations — AND within a filter
# ---------------------------------------------------------------------------


def test_magnitude_and_bbox_both_pass() -> None:
    f = _filter(min_magnitude=4.0, **_BBOX_KWARGS)
    assert matches(f, _event(magnitude=5.0, latitude=37.0, longitude=23.0))


def test_magnitude_and_bbox_one_fails_drops_match() -> None:
    """High magnitude but outside bbox → no match."""
    f = _filter(min_magnitude=4.0, **_BBOX_KWARGS)
    assert not matches(f, _event(magnitude=5.0, latitude=50.0, longitude=23.0))


def test_magnitude_and_bbox_both_fail() -> None:
    """Low magnitude AND outside bbox → no match."""
    f = _filter(min_magnitude=4.0, **_BBOX_KWARGS)
    assert not matches(f, _event(magnitude=2.0, latitude=50.0, longitude=23.0))


def test_magnitude_and_center_radius_combined() -> None:
    f = _filter(min_magnitude=4.0, **_CENTER_KWARGS)
    # In radius, mag passes:
    assert matches(f, _event(magnitude=4.5, latitude=37.05, longitude=23.05))
    # In radius, mag fails:
    assert not matches(f, _event(magnitude=3.0, latitude=37.05, longitude=23.05))
    # Out of radius, mag passes:
    assert not matches(f, _event(magnitude=4.5, latitude=40.0, longitude=23.0))


# ---------------------------------------------------------------------------
# empty filter — matches everything (validator rejects this at API layer)
# ---------------------------------------------------------------------------


def test_empty_filter_matches_any_event() -> None:
    """No predicate set → matches everything.

    The :class:`models.alerts.AlertFilter` validator rejects empty
    filters at the API boundary (Task 1's `test_filter_empty_payload_
    is_rejected`), so we never see one of these in production. The
    matcher's "vacuously true" behavior is documented for callers
    constructing filter rows programmatically (e.g. seeded test data).
    """
    assert matches(_filter(), _event(magnitude=0.1, latitude=89.0, longitude=-179.0))


# ---------------------------------------------------------------------------
# all predicates set
# ---------------------------------------------------------------------------


def test_all_predicates_set_all_pass() -> None:
    """A filter that constrains magnitude AND bbox AND center+radius simultaneously."""
    # Note: bbox and center+radius coexist in the DB row (the API
    # validator rejects this combination, but the row model is
    # accommodating — so the matcher's AND semantics must still hold
    # if someone constructs such a row directly).
    f = _filter(min_magnitude=4.0, **_BBOX_KWARGS, **_CENTER_KWARGS)
    assert matches(f, _event(magnitude=5.0, latitude=37.0, longitude=23.0))


def test_all_predicates_set_radius_fails() -> None:
    f = _filter(min_magnitude=4.0, **_BBOX_KWARGS, **_CENTER_KWARGS)
    # Inside bbox + above magnitude, but outside the 100 km radius.
    assert not matches(f, _event(magnitude=5.0, latitude=38.0, longitude=24.0))
