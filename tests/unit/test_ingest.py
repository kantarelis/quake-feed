"""Unit tests for :func:`quake.events.ingest.poll_once`.

Runs against the session-scoped sandbox container from
``tests/conftest.py``. ``UsgsClient.fetch`` is monkeypatched so no real
USGS round-trip happens.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from prometheus_client import REGISTRY

from database.etls.endpoint_locks import EndpointLocksETL
from database.etls.events import EventsETL
from database.etls.ingestion_runs import IngestionRunsETL
from database.etls.revisions import RevisionsETL
from quake.events.ingest import poll_once
from quake.ingestion.usgs.client import UsgsClient

_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "usgs_all_hour.json"

# Catalogue samples touched by poll_once. Counters are process-global, so the
# metric tests below assert *deltas* around a single call rather than absolutes.
_METRIC_SAMPLES = (
    "events_inserted_total",
    "events_updated_total",
    "events_revisions_total",
    "usgs_poll_errors_total",
    "usgs_poll_seconds_count",
)


def _metric_snapshot() -> dict[str, float]:
    return {name: (REGISTRY.get_sample_value(name) or 0.0) for name in _METRIC_SAMPLES}


@pytest.fixture
def fixture_dict() -> dict[str, Any]:
    return json.loads(_FIXTURE_PATH.read_text())


@pytest.fixture
def patch_fetch(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, Any]], None]:
    """Return a helper that monkeypatches ``UsgsClient.fetch`` to a fixed payload."""

    def _patch(payload: dict[str, Any]) -> None:
        def _fake_fetch(self: UsgsClient, feed: Any) -> dict[str, Any]:
            return payload

        monkeypatch.setattr(UsgsClient, "fetch", _fake_fetch)

    return _patch


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_happy_path_inserts_and_records_run(
    fixture_dict: dict[str, Any],
    patch_fetch: Callable[[dict[str, Any]], None],
) -> None:
    patch_fetch(fixture_dict)
    result = poll_once()

    feature_count = len(fixture_dict["features"])
    assert result.inserted == feature_count
    assert result.updated == 0
    assert result.revisions == 0
    assert result.error is None

    # ingestion_runs row complete
    runs = IngestionRunsETL().latest(1)
    assert runs[0].finished_at is not None
    assert runs[0].inserted_count == feature_count
    assert runs[0].updated_count == 0
    assert runs[0].revision_count == 0
    assert runs[0].error is None

    # events actually landed
    assert len(EventsETL().recent(feature_count + 1)) == feature_count


# ---------------------------------------------------------------------------
# idempotent re-run
# ---------------------------------------------------------------------------


def test_second_call_with_same_data_updates_zero_inserts(
    fixture_dict: dict[str, Any],
    patch_fetch: Callable[[dict[str, Any]], None],
) -> None:
    patch_fetch(fixture_dict)
    poll_once()  # first call: all inserts

    second = poll_once()
    feature_count = len(fixture_dict["features"])
    assert second.inserted == 0
    assert second.updated == feature_count
    # no field changes → trigger doesn't fire any revisions
    assert second.revisions == 0


# ---------------------------------------------------------------------------
# revision detection
# ---------------------------------------------------------------------------


def test_above_threshold_magnitude_change_produces_one_revision(
    fixture_dict: dict[str, Any],
    patch_fetch: Callable[[dict[str, Any]], None],
) -> None:
    """Bumping one event's mag by +0.3 (above the 0.1 trigger threshold) writes one revision."""
    patch_fetch(fixture_dict)
    poll_once()  # seed

    mutated = copy.deepcopy(fixture_dict)
    mutated["features"][0]["properties"]["mag"] += 0.3
    patch_fetch(mutated)
    result = poll_once()

    feature_count = len(fixture_dict["features"])
    assert result.inserted == 0
    assert result.updated == feature_count
    assert result.revisions == 1

    # cross-check via RevisionsETL
    revs = RevisionsETL().for_event(fixture_dict["features"][0]["id"])
    assert len(revs) == 1


# ---------------------------------------------------------------------------
# error path
# ---------------------------------------------------------------------------


def test_error_path_records_error_and_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(self: UsgsClient, feed: Any) -> dict[str, Any]:
        raise RuntimeError("boom from USGS")

    monkeypatch.setattr(UsgsClient, "fetch", _boom)

    with pytest.raises(RuntimeError, match="boom"):
        poll_once()

    runs = IngestionRunsETL().latest(1)
    assert runs[0].error == "boom from USGS"
    assert runs[0].finished_at is not None
    assert runs[0].inserted_count == 0
    assert runs[0].updated_count == 0
    assert runs[0].revision_count == 0


# ---------------------------------------------------------------------------
# kill-switch gate (INGESTION_LOCK)
# ---------------------------------------------------------------------------


def test_poll_skips_when_ingestion_lock_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lock set → record a skip-marker run, do NOT call USGS, return error envelope."""
    EndpointLocksETL().set_lock("INGESTION_LOCK", locked_by="test", reason="testing")

    fetch_calls: list[Any] = []

    def _track_fetch(self: UsgsClient, feed: Any) -> dict[str, Any]:
        fetch_calls.append(feed)
        return {"features": []}

    monkeypatch.setattr(UsgsClient, "fetch", _track_fetch)

    result = poll_once()
    assert result.inserted == 0
    assert result.updated == 0
    assert result.revisions == 0
    assert result.error == "INGESTION_LOCK active"
    assert fetch_calls == []  # USGS never contacted

    runs = IngestionRunsETL().latest(1)
    assert runs[0].error == "INGESTION_LOCK active"
    assert runs[0].finished_at is not None
    assert runs[0].inserted_count == 0


# ---------------------------------------------------------------------------
# Prometheus metric deltas
# ---------------------------------------------------------------------------


def test_metrics_incremented_on_successful_poll(
    fixture_dict: dict[str, Any],
    patch_fetch: Callable[[dict[str, Any]], None],
) -> None:
    patch_fetch(fixture_dict)
    before = _metric_snapshot()
    poll_once()
    after = _metric_snapshot()

    feature_count = len(fixture_dict["features"])
    assert after["events_inserted_total"] - before["events_inserted_total"] == feature_count
    assert after["events_updated_total"] - before["events_updated_total"] == 0
    assert after["events_revisions_total"] - before["events_revisions_total"] == 0
    assert after["usgs_poll_errors_total"] - before["usgs_poll_errors_total"] == 0
    assert after["usgs_poll_seconds_count"] - before["usgs_poll_seconds_count"] == 1


def test_metrics_increment_error_counter_on_failed_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(self: UsgsClient, feed: Any) -> dict[str, Any]:
        raise RuntimeError("boom from USGS")

    monkeypatch.setattr(UsgsClient, "fetch", _boom)

    before = _metric_snapshot()
    with pytest.raises(RuntimeError, match="boom"):
        poll_once()
    after = _metric_snapshot()

    assert after["usgs_poll_errors_total"] - before["usgs_poll_errors_total"] == 1
    # event counters untouched on the error path
    assert after["events_inserted_total"] - before["events_inserted_total"] == 0
    assert after["events_updated_total"] - before["events_updated_total"] == 0
    assert after["events_revisions_total"] - before["events_revisions_total"] == 0
    # the timer wraps the failing block, so the duration is still observed
    assert after["usgs_poll_seconds_count"] - before["usgs_poll_seconds_count"] == 1


def test_metrics_unchanged_on_lock_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    EndpointLocksETL().set_lock("INGESTION_LOCK", locked_by="test", reason="testing")

    def _track_fetch(self: UsgsClient, feed: Any) -> dict[str, Any]:
        return {"features": []}

    monkeypatch.setattr(UsgsClient, "fetch", _track_fetch)

    before = _metric_snapshot()
    poll_once()
    after = _metric_snapshot()

    # lock-skip returns before the timer/counters, so nothing moves
    for name in _METRIC_SAMPLES:
        assert after[name] - before[name] == 0, name
