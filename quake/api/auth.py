"""API-key authentication primitives.

The on-the-wire credential is an opaque random string in the
``qkf_<32 hex chars>`` format. Its SHA-256 hash is stored in
``quake.api_keys``; the raw value is held under
``secret/api-keys/<id>`` in Vault.

The :class:`Authenticate` dependency validates a Bearer header by:

1. parsing the header,
2. hashing the raw key with SHA-256,
3. looking up the row whose ``key_hash`` matches,
4. refusing rows with a non-NULL ``revoked_at``,
5. cross-checking the raw value against the Vault path for that id,
6. refusing rows missing the required scope,
7. touching ``last_seen_at``, and
8. returning the :class:`ApiKeyRow` for downstream views.

Steps 3 and 5 are both required: a DB-only or Vault-only compromise
must not be enough to forge a valid key.
"""

from __future__ import annotations

import hashlib
import secrets
from functools import lru_cache
from typing import Protocol

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from database.etls.api_keys import ApiKeysETL
from database.models import ApiKeyRow
from functions.environment import get_environmental_variables
from functions.vault import VaultClient

_KEY_PREFIX = "qkf_"
_KEY_BYTES = 16  # secrets.token_hex(16) → 32 hex chars
_VAULT_PATH_PREFIX = "api-keys"

_bearer = HTTPBearer(auto_error=False)


class _VaultReader(Protocol):
    """Minimal surface :class:`Authenticate` needs from a Vault client.

    Typed structurally so tests can pass a lightweight in-process stub
    without inheriting from :class:`functions.vault.VaultClient`.
    """

    def get_secret(self, path: str, key: str) -> str | None: ...


def hash_key(raw: str) -> str:
    """Return the canonical SHA-256 hex digest of a raw API key."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_raw_key() -> str:
    """Mint a fresh raw key in the ``qkf_<hex32>`` format."""
    return f"{_KEY_PREFIX}{secrets.token_hex(_KEY_BYTES)}"


def vault_path(key_id: int) -> str:
    """Vault KV-v2 path holding the raw key for a given DB row id."""
    return f"{_VAULT_PATH_PREFIX}/{key_id}"


@lru_cache(maxsize=1)
def get_vault_client() -> VaultClient:
    """Lazy-init the Vault client used by :class:`Authenticate`.

    Memoised so each request reuses one client instance. FastAPI tests
    override this via ``app.dependency_overrides`` to swap in a stub.
    """
    cfg = get_environmental_variables().vault
    token = cfg.token or cfg.dev_root_token_id
    return VaultClient(address=cfg.address, token=token)


class Authenticate:
    """FastAPI dependency that validates an API-key Bearer header.

    Usage::

        @router.get("/...", dependencies=[Depends(Authenticate())])
        @router.post(
            "/admin/...",
            dependencies=[Depends(Authenticate(required_scope="admin"))],
        )

    Pass ``required_scope`` to demand a scope; omit it for "any valid
    key".
    """

    def __init__(self, *, required_scope: str | None = None) -> None:
        self._required_scope = required_scope

    async def __call__(
        self,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
        vault: _VaultReader = Depends(get_vault_client),
    ) -> ApiKeyRow:
        if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing or malformed Authorization header",
            )

        raw = credentials.credentials
        api_keys = ApiKeysETL()
        row = api_keys.get_by_hash(hash_key(raw))
        if row is None or row.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid api key",
            )

        stored_raw = vault.get_secret(vault_path(row.id), "raw_key")
        if stored_raw is None or not secrets.compare_digest(stored_raw, raw):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid api key",
            )

        if self._required_scope is not None and self._required_scope not in row.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing required scope: {self._required_scope}",
            )

        api_keys.touch_last_seen(row.id)
        return row
