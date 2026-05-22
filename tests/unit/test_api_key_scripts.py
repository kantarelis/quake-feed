"""Unit tests for the issue/revoke API-key scripts.

Calls the script entry points (``issue``, ``revoke``) directly against
the sandbox DB and a :class:`StubVault`, so no subprocess and no live
Vault container are needed. The end-to-end CLI surface is exercised
indirectly in the integration smoke (Task 7).
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from database.etls.api_keys import ApiKeysETL
from quake.api.auth import hash_key, vault_path
from scripts.issue_api_key import issue
from scripts.list_api_keys import list_keys
from scripts.prune_api_keys import prune
from scripts.revoke_api_key import revoke
from tests._auth import StubVault


@pytest.fixture
def vault() -> StubVault:
    return StubVault()


class _FailingPutVault(StubVault):
    """Vault stub that explodes on ``put_secret`` — exercises the rollback path."""

    def put_secret(self, path: str, payload: dict[str, str]) -> None:
        raise RuntimeError("simulated vault outage")


# ---------------------------------------------------------------------------
# issue
# ---------------------------------------------------------------------------


def test_issue_inserts_db_row_and_vault_path(vault: StubVault) -> None:
    buf = io.StringIO()
    key_id = issue(label="alice", scopes=["admin"], vault=vault, stdout=buf)

    row = ApiKeysETL().get_by_id(key_id)
    assert row is not None
    assert row.label == "alice"
    assert row.scopes == ["admin"]
    assert row.revoked_at is None

    stored = vault.get_secret(vault_path(key_id), "raw_key")
    assert stored is not None
    assert stored.startswith("qkf_")
    assert hash_key(stored) == row.key_hash


def test_issue_prints_raw_key_once(vault: StubVault) -> None:
    buf = io.StringIO()
    issue(label="dev", scopes=[], vault=vault, stdout=buf)

    text = buf.getvalue()
    raw_lines = [ln for ln in text.splitlines() if ln.startswith("qkf_")]
    assert len(raw_lines) == 1
    assert "cannot be recovered" in text


def test_issue_rolls_back_db_on_vault_failure() -> None:
    """Vault failure → DB row is hard-deleted, not just revoked."""
    api_keys_before = ApiKeysETL()
    # Snapshot row ids that exist before; rollback should leave the set unchanged.
    initial: list[Any] = api_keys_before._execute("SELECT id FROM quake.api_keys", fetch="all")
    initial_ids = {r["id"] for r in initial}

    failing = _FailingPutVault()
    with pytest.raises(RuntimeError, match="simulated vault outage"):
        issue(label="will-fail", scopes=[], vault=failing, stdout=io.StringIO())

    after: list[Any] = api_keys_before._execute("SELECT id FROM quake.api_keys", fetch="all")
    after_ids = {r["id"] for r in after}
    assert after_ids == initial_ids


# ---------------------------------------------------------------------------
# revoke
# ---------------------------------------------------------------------------


def test_revoke_marks_db_and_destroys_vault(vault: StubVault) -> None:
    key_id = issue(label="t", scopes=[], vault=vault, stdout=io.StringIO())
    assert vault.get_secret(vault_path(key_id), "raw_key") is not None

    rc = revoke(key_id=key_id, vault=vault, stdout=io.StringIO(), stderr=io.StringIO())
    assert rc == 0

    row = ApiKeysETL().get_by_id(key_id)
    assert row is not None
    assert row.revoked_at is not None
    assert vault.get_secret(vault_path(key_id), "raw_key") is None


def test_revoke_is_idempotent(vault: StubVault) -> None:
    key_id = issue(label="t", scopes=[], vault=vault, stdout=io.StringIO())
    assert revoke(key_id=key_id, vault=vault, stdout=io.StringIO(), stderr=io.StringIO()) == 0

    buf = io.StringIO()
    rc = revoke(key_id=key_id, vault=vault, stdout=buf, stderr=io.StringIO())
    assert rc == 0
    assert "already revoked" in buf.getvalue()


def test_revoke_unknown_id_returns_2(vault: StubVault) -> None:
    err = io.StringIO()
    rc = revoke(key_id=999_999, vault=vault, stdout=io.StringIO(), stderr=err)
    assert rc == 2
    assert "no such key_id" in err.getvalue()


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_keys_empty(vault: StubVault) -> None:
    buf = io.StringIO()
    assert list_keys(stdout=buf) == 0
    assert "no API keys issued" in buf.getvalue()


def test_list_keys_shows_ids_labels_and_status_without_raw(vault: StubVault) -> None:
    active_id = issue(label="alice", scopes=["admin"], vault=vault, stdout=io.StringIO())
    revoked_id = issue(label="bob", scopes=[], vault=vault, stdout=io.StringIO())
    revoke(key_id=revoked_id, vault=vault, stdout=io.StringIO(), stderr=io.StringIO())

    buf = io.StringIO()
    assert list_keys(stdout=buf) == 0
    text = buf.getvalue()

    assert str(active_id) in text and "alice" in text and "admin" in text
    assert "active" in text
    assert "revoked" in text  # bob's row
    # the raw key (qkf_...) must never appear in a listing
    assert "qkf_" not in text


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


def test_prune_none_message(vault: StubVault) -> None:
    issue(label="keep", scopes=[], vault=vault, stdout=io.StringIO())  # active only
    buf = io.StringIO()
    assert prune(stdout=buf) == 0
    assert "no revoked keys to prune" in buf.getvalue()


def test_prune_removes_only_revoked_keys(vault: StubVault) -> None:
    active_id = issue(label="keep", scopes=[], vault=vault, stdout=io.StringIO())
    revoked_id = issue(label="gone", scopes=[], vault=vault, stdout=io.StringIO())
    revoke(key_id=revoked_id, vault=vault, stdout=io.StringIO(), stderr=io.StringIO())

    buf = io.StringIO()
    assert prune(stdout=buf) == 0
    assert "pruned 1 revoked key(s)" in buf.getvalue()

    assert ApiKeysETL().get_by_id(active_id) is not None
    assert ApiKeysETL().get_by_id(revoked_id) is None
