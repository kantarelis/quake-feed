"""Unit tests for :mod:`quake.api.auth`.

Calls :class:`Authenticate` directly (not via the FastAPI request
pipeline) so each scenario can isolate the credential, the DB row,
the Vault payload, and the required scope. End-to-end HTTP coverage
through ``TestClient`` arrives in Task 3 (route retrofit) and Task 7
(integration smoke).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from database.etls.api_keys import ApiKeysETL
from quake.api.auth import Authenticate, generate_raw_key, hash_key, vault_path
from tests._auth import StubVault, issue_test_key


@pytest.fixture
def vault() -> StubVault:
    return StubVault()


def _bearer(raw: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw)


@pytest.mark.asyncio
async def test_no_header_is_401(vault: StubVault) -> None:
    with pytest.raises(HTTPException) as exc:
        await Authenticate()(credentials=None, vault=vault)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_wrong_scheme_is_401(vault: StubVault) -> None:
    creds = HTTPAuthorizationCredentials(scheme="Basic", credentials="something")
    with pytest.raises(HTTPException) as exc:
        await Authenticate()(credentials=creds, vault=vault)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_unknown_key_is_401(vault: StubVault) -> None:
    """Well-formed key that was never issued — no DB row → 401."""
    with pytest.raises(HTTPException) as exc:
        await Authenticate()(credentials=_bearer(generate_raw_key()), vault=vault)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_revoked_key_is_401(vault: StubVault) -> None:
    raw, _ = issue_test_key(vault=vault)
    row = ApiKeysETL().get_by_hash(hash_key(raw))
    assert row is not None
    ApiKeysETL().revoke(row.id)

    with pytest.raises(HTTPException) as exc:
        await Authenticate()(credentials=_bearer(raw), vault=vault)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_scope_is_403(vault: StubVault) -> None:
    raw, _ = issue_test_key(vault=vault, scopes=[])
    with pytest.raises(HTTPException) as exc:
        await Authenticate(required_scope="admin")(credentials=_bearer(raw), vault=vault)
    assert exc.value.status_code == 403
    assert "admin" in exc.value.detail


@pytest.mark.asyncio
async def test_valid_key_returns_row_and_updates_last_seen(vault: StubVault) -> None:
    raw, _ = issue_test_key(vault=vault)

    row = await Authenticate()(credentials=_bearer(raw), vault=vault)
    assert row.key_hash == hash_key(raw)
    assert row.revoked_at is None

    # The returned row is the pre-touch snapshot; verify the DB-side touch
    # by re-fetching.
    refetched = ApiKeysETL().get_by_hash(hash_key(raw))
    assert refetched is not None
    assert refetched.last_seen_at is not None


@pytest.mark.asyncio
async def test_admin_scope_passes_when_required(vault: StubVault) -> None:
    raw, _ = issue_test_key(vault=vault, scopes=["admin"])
    row = await Authenticate(required_scope="admin")(credentials=_bearer(raw), vault=vault)
    assert "admin" in row.scopes


@pytest.mark.asyncio
async def test_vault_mismatch_is_401(vault: StubVault) -> None:
    """DB hash matches but Vault stores a different raw — partial rotation / compromise → fail closed."""
    raw, _ = issue_test_key(vault=vault)
    row = ApiKeysETL().get_by_hash(hash_key(raw))
    assert row is not None
    # Overwrite the Vault entry to simulate divergence.
    vault.put_secret(vault_path(row.id), {"raw_key": generate_raw_key()})

    with pytest.raises(HTTPException) as exc:
        await Authenticate()(credentials=_bearer(raw), vault=vault)
    assert exc.value.status_code == 401
