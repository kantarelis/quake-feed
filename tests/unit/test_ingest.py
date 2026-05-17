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

from database.etls.events import EventsETL
from database.etls.ingestion_runs import IngestionRunsETL
from database.etls.revisions import RevisionsETL
from quake.events.ingest import poll_once
from quake.ingestion.usgs.client import UsgsClient

_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "usgs_all_hour.json"


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
