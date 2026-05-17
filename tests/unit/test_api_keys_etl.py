"""Unit tests for ApiKeysETL.

Round-trip coverage of insert / get / touch_last_seen / revoke.
Runs against the session-scoped sandbox container from
``tests/conftest.py``.
"""

from __future__ import annotations

import time

import psycopg
import pytest

from database.etls.api_keys import ApiKeysETL


@pytest.fixture
def keys() -> ApiKeysETL:
    return ApiKeysETL()


def test_insert_returns_positive_id(keys: ApiKeysETL) -> None:
    key_id = keys.insert("hash-abc", label="primary", scopes=["read"])
    assert isinstance(key_id, int)
    assert key_id > 0


def test_get_by_hash_round_trips_every_field(keys: ApiKeysETL) -> None:
    key_id = keys.insert("hash-abc", label="primary", scopes=["read", "admin"])

    row = keys.get_by_hash("hash-abc")
    assert row is not None
    assert row.id == key_id
    assert row.key_hash == "hash-abc"
    assert row.label == "primary"
    assert row.scopes == ["read", "admin"]
    assert row.last_seen_at is None
    assert row.revoked_at is None


def test_get_by_hash_miss_returns_none(keys: ApiKeysETL) -> None:
    assert keys.get_by_hash("never-inserted") is None


def test_insert_supports_null_label_and_empty_scopes(keys: ApiKeysETL) -> None:
    key_id = keys.insert("hash-minimal", label=None, scopes=[])
    row = keys.get_by_hash("hash-minimal")
    assert row is not None
    assert row.id == key_id
    assert row.label is None
    assert row.scopes == []


def test_duplicate_key_hash_raises(keys: ApiKeysETL) -> None:
    """The UNIQUE constraint on key_hash protects against accidental double-issue."""
    keys.insert("hash-dup", label=None, scopes=[])
    with pytest.raises(psycopg.errors.UniqueViolation):
        keys.insert("hash-dup", label=None, scopes=[])


def test_touch_last_seen_populates_timestamp(keys: ApiKeysETL) -> None:
    key_id = keys.insert("hash-touch", label=None, scopes=[])

    before = keys.get_by_hash("hash-touch")
    assert before is not None
    assert before.last_seen_at is None

    keys.touch_last_seen(key_id)

    after = keys.get_by_hash("hash-touch")
    assert after is not None
    assert after.last_seen_at is not None


def test_revoke_sets_revoked_at(keys: ApiKeysETL) -> None:
    key_id = keys.insert("hash-revoke", label=None, scopes=[])
    keys.revoke(key_id)

    row = keys.get_by_hash("hash-revoke")
    assert row is not None
    assert row.revoked_at is not None


def test_revoke_is_idempotent(keys: ApiKeysETL) -> None:
    """Re-revoking must not bump revoked_at — the original revocation time is the source of truth."""
    key_id = keys.insert("hash-idempotent", label=None, scopes=[])
    keys.revoke(key_id)

    first = keys.get_by_hash("hash-idempotent")
    assert first is not None and first.revoked_at is not None
    first_ts = first.revoked_at

    time.sleep(0.01)  # ensure now() would differ if a naive UPDATE fired
    keys.revoke(key_id)

    second = keys.get_by_hash("hash-idempotent")
    assert second is not None and second.revoked_at == first_ts
