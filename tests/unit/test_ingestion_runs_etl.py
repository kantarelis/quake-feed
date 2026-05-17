"""Unit tests for IngestionRunsETL.

Runs against the session-scoped sandbox container from
``tests/conftest.py``. Each test starts with empty tables.
"""

from __future__ import annotations

import pytest

from database.etls.ingestion_runs import IngestionRunsETL


@pytest.fixture
def runs() -> IngestionRunsETL:
    return IngestionRunsETL()


def test_start_run_returns_int_id(runs: IngestionRunsETL) -> None:
    run_id = runs.start_run()
    assert isinstance(run_id, int)
    assert run_id > 0


def test_start_then_finish_records_counts(runs: IngestionRunsETL) -> None:
    """A started run has NULL finished_at and zero counts; finish populates both."""
    run_id = runs.start_run()

    fresh = runs.latest(1)
    assert len(fresh) == 1
    assert fresh[0].id == run_id
    assert fresh[0].finished_at is None
    assert fresh[0].inserted_count == 0
    assert fresh[0].updated_count == 0
    assert fresh[0].revision_count == 0
    assert fresh[0].error is None

    runs.finish_run(run_id, inserted=7, updated=3, revisions=1)

    after = runs.latest(1)
    assert after[0].id == run_id
    assert after[0].finished_at is not None
    assert after[0].inserted_count == 7
    assert after[0].updated_count == 3
    assert after[0].revision_count == 1
    assert after[0].error is None


def test_finish_run_records_error_string(runs: IngestionRunsETL) -> None:
    run_id = runs.start_run()
    runs.finish_run(run_id, inserted=0, updated=0, revisions=0, error="USGS 503")

    row = runs.latest(1)[0]
    assert row.error == "USGS 503"
    assert row.finished_at is not None


def test_latest_orders_by_started_at_desc(runs: IngestionRunsETL) -> None:
    ids = [runs.start_run() for _ in range(3)]
    out = runs.latest(5)
    # BIGSERIAL is monotonic and started_at is now() per insert; newest run last started, listed first.
    assert [r.id for r in out] == list(reversed(ids))


def test_latest_respects_limit(runs: IngestionRunsETL) -> None:
    for _ in range(5):
        runs.start_run()
    assert len(runs.latest(2)) == 2
