"""Unit tests for :class:`EndpointLocksETL`.

``INGESTION_LOCK`` is seeded by the conftest's ``_clean_tables``
fixture before every test, so each test starts with that row present
and ``is_locked=false``.
"""

from __future__ import annotations

import pytest

from database.etls.endpoint_locks import EndpointLocksETL


@pytest.fixture
def locks() -> EndpointLocksETL:
    return EndpointLocksETL()


def test_list_all_returns_seeded_lock(locks: EndpointLocksETL) -> None:
    rows = locks.list_all()
    names = {r.lock_name for r in rows}
    assert "INGESTION_LOCK" in names


def test_is_locked_returns_false_for_freshly_seeded_lock(locks: EndpointLocksETL) -> None:
    assert locks.is_locked("INGESTION_LOCK") is False


def test_is_locked_returns_false_for_unknown_name(locks: EndpointLocksETL) -> None:
    """Unknown lock fails open — see module docstring rationale."""
    assert locks.is_locked("DOES_NOT_EXIST") is False


def test_set_lock_updates_existing_row(locks: EndpointLocksETL) -> None:
    row = locks.set_lock("INGESTION_LOCK", locked_by="alice", reason="maintenance")
    assert row is not None
    assert row.is_locked is True
    assert row.locked_by == "alice"
    assert row.reason == "maintenance"
    assert row.locked_at is not None

    # Cross-check via is_locked
    assert locks.is_locked("INGESTION_LOCK") is True


def test_set_lock_unknown_name_returns_none(locks: EndpointLocksETL) -> None:
    assert locks.set_lock("DOES_NOT_EXIST", locked_by="alice", reason="x") is None


def test_clear_lock_resets_fields(locks: EndpointLocksETL) -> None:
    locks.set_lock("INGESTION_LOCK", locked_by="alice", reason="maintenance")
    row = locks.clear_lock("INGESTION_LOCK")
    assert row is not None
    assert row.is_locked is False
    assert row.locked_by is None
    assert row.locked_at is None
    assert row.reason is None
    assert locks.is_locked("INGESTION_LOCK") is False


def test_clear_lock_unknown_name_returns_none(locks: EndpointLocksETL) -> None:
    assert locks.clear_lock("DOES_NOT_EXIST") is None


def test_set_lock_is_overwrite_semantics(locks: EndpointLocksETL) -> None:
    """A second set_lock replaces locked_by / reason rather than no-oping."""
    locks.set_lock("INGESTION_LOCK", locked_by="alice", reason="first")
    row = locks.set_lock("INGESTION_LOCK", locked_by="bob", reason="second")
    assert row is not None
    assert row.locked_by == "bob"
    assert row.reason == "second"
