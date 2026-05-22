"""Unit tests for :mod:`functions.metrics`.

Importing the module is the only registration step, so these assert that the
catalogue metrics land on the default registry under their expected sample
names and types.
"""

from __future__ import annotations

from prometheus_client import REGISTRY, Counter, Histogram

import functions.metrics as metrics

_EXPECTED_SAMPLES = (
    "usgs_poll_seconds_count",
    "usgs_poll_errors_total",
    "events_inserted_total",
    "events_updated_total",
    "events_revisions_total",
)


def test_catalogue_metrics_registered_on_default_registry() -> None:
    """Every catalogue sample resolves on the default registry (>=0.0, not absent)."""
    for sample in _EXPECTED_SAMPLES:
        assert REGISTRY.get_sample_value(sample) is not None, sample


def test_metric_types_match_catalogue() -> None:
    assert isinstance(metrics.USGS_POLL_SECONDS, Histogram)
    assert isinstance(metrics.USGS_POLL_ERRORS_TOTAL, Counter)
    assert isinstance(metrics.EVENTS_INSERTED_TOTAL, Counter)
    assert isinstance(metrics.EVENTS_UPDATED_TOTAL, Counter)
    assert isinstance(metrics.EVENTS_REVISIONS_TOTAL, Counter)
