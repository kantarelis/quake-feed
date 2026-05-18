"""Shared auth helpers for tests.

Exposes:

* :class:`StubVault` — an in-process stand-in for
  :class:`functions.vault.VaultClient`. Mirrors the same surface used by
  :mod:`quake.api.auth` (``get_secret`` / ``put_secret`` / ``list_keys``)
  so tests can swap it in via ``app.dependency_overrides`` or by passing
  it directly into :class:`quake.api.auth.Authenticate`.
* :func:`issue_test_key` — one-shot helper that mints a key directly
  into the sandbox DB + stub vault and returns the raw key together
  with a ready-to-use ``Authorization`` header dict.

The stub mirrors :class:`functions.vault.VaultClient` 1:1 for the
methods :mod:`quake.api.auth` and the issue/revoke scripts use:
``get_secret``, ``put_secret``, ``list_keys``, ``delete_secret``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from database.etls.api_keys import ApiKeysETL
from quake.api.auth import generate_raw_key, hash_key, vault_path


class StubVault:
    """In-process stand-in for :class:`functions.vault.VaultClient`."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, str]] = {}

    def get_secret(self, path: str, key: str) -> str | None:
        return self._store.get(path, {}).get(key)

    def put_secret(self, path: str, payload: dict[str, str]) -> None:
        self._store[path] = dict(payload)

    def list_keys(self, path: str) -> list[str]:
        prefix = path.rstrip("/") + "/"
        return [k.removeprefix(prefix).split("/")[0] for k in self._store if k.startswith(prefix)]

    def delete_secret(self, path: str) -> None:
        self._store.pop(path, None)


def issue_test_key(
    *,
    vault: StubVault,
    scopes: list[str] | None = None,
    label: str | None = "test",
) -> tuple[str, dict[str, str]]:
    """Persist a fresh key into the sandbox DB + ``vault``.

    Returns ``(raw_key, headers)`` where ``headers`` is ready to splat
    into ``client.get(..., headers=headers)`` from a ``TestClient``.
    """
    raw = generate_raw_key()
    key_id = ApiKeysETL().insert(
        key_hash=hash_key(raw),
        label=label,
        scopes=list(scopes or []),
    )
    vault.put_secret(
        vault_path(key_id),
        {
            "raw_key": raw,
            "label": label or "",
            "issued_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return raw, {"Authorization": f"Bearer {raw}"}
