"""Unit tests for AlertFiltersETL.

Round-trip coverage of insert / for_api_key / update / delete plus the
cross-key defence in update/delete WHERE clauses. Runs against the
session-scoped sandbox container from ``tests/conftest.py``.
"""

from __future__ import annotations

import pytest

from database.etls.alert_filters import AlertFiltersETL
from database.etls.api_keys import ApiKeysETL


@pytest.fixture
def filters() -> AlertFiltersETL:
    return AlertFiltersETL()


@pytest.fixture
def api_key_id() -> int:
    """A real API key id for FK satisfaction. CASCADE on the FK means
    truncating api_keys (per-test conftest) wipes filters too."""
    return ApiKeysETL().insert("hash-owner", label=None, scopes=[])


@pytest.fixture
def other_api_key_id() -> int:
    """A second key id for cross-key defence tests."""
    return ApiKeysETL().insert("hash-other", label=None, scopes=[])


# ---------------------------------------------------------------------------
# insert / for_api_key
# ---------------------------------------------------------------------------


def test_insert_returns_positive_id_and_persists(filters: AlertFiltersETL, api_key_id: int) -> None:
    fid = filters.insert(api_key_id, min_magnitude=3.5, center_lat=37.0, center_lon=-122.0, radius_km=50.0)
    assert fid > 0

    out = filters.for_api_key(api_key_id)
    assert len(out) == 1
    assert out[0].id == fid
    assert out[0].api_key_id == api_key_id
    assert out[0].min_magnitude == 3.5
    assert out[0].center_lat == 37.0
    assert out[0].center_lon == -122.0
    assert out[0].radius_km == 50.0
    # bbox columns untouched on a center+radius insert
    assert out[0].bbox_min_lat is None
    assert out[0].bbox_max_lat is None


def test_insert_with_all_nulls_succeeds(filters: AlertFiltersETL, api_key_id: int) -> None:
    """A filter row may legitimately have every shape column NULL (e.g. 'any event' subscription)."""
    fid = filters.insert(api_key_id)
    out = filters.for_api_key(api_key_id)
    assert out[0].id == fid
    assert out[0].min_magnitude is None


def test_for_api_key_scoped_to_owner(filters: AlertFiltersETL, api_key_id: int, other_api_key_id: int) -> None:
    filters.insert(api_key_id, min_magnitude=2.0)
    filters.insert(other_api_key_id, min_magnitude=4.0)

    mine = filters.for_api_key(api_key_id)
    theirs = filters.for_api_key(other_api_key_id)

    assert [f.min_magnitude for f in mine] == [2.0]
    assert [f.min_magnitude for f in theirs] == [4.0]


def test_for_api_key_returns_empty_list_for_unknown_key(filters: AlertFiltersETL) -> None:
    assert filters.for_api_key(999_999) == []


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_modifies_row_returns_true(filters: AlertFiltersETL, api_key_id: int) -> None:
    fid = filters.insert(api_key_id, min_magnitude=2.0)

    ok = filters.update(fid, api_key_id, min_magnitude=5.5, radius_km=100.0)
    assert ok is True

    row = filters.for_api_key(api_key_id)[0]
    assert row.min_magnitude == 5.5
    assert row.radius_km == 100.0


def test_update_cross_key_returns_false(filters: AlertFiltersETL, api_key_id: int, other_api_key_id: int) -> None:
    """Updating filter X while passing the wrong api_key_id must be a no-op."""
    fid = filters.insert(api_key_id, min_magnitude=2.0)

    ok = filters.update(fid, other_api_key_id, min_magnitude=99.0)
    assert ok is False

    row = filters.for_api_key(api_key_id)[0]
    assert row.min_magnitude == 2.0


def test_update_unknown_filter_returns_false(filters: AlertFiltersETL, api_key_id: int) -> None:
    assert filters.update(999_999, api_key_id, min_magnitude=1.0) is False


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_returns_true_and_removes_row(filters: AlertFiltersETL, api_key_id: int) -> None:
    fid = filters.insert(api_key_id, min_magnitude=2.0)
    assert filters.delete(fid, api_key_id) is True
    assert filters.for_api_key(api_key_id) == []


def test_delete_cross_key_returns_false(filters: AlertFiltersETL, api_key_id: int, other_api_key_id: int) -> None:
    fid = filters.insert(api_key_id, min_magnitude=2.0)
    assert filters.delete(fid, other_api_key_id) is False
    # the row is still there
    assert len(filters.for_api_key(api_key_id)) == 1


def test_delete_unknown_filter_returns_false(filters: AlertFiltersETL, api_key_id: int) -> None:
    assert filters.delete(999_999, api_key_id) is False
