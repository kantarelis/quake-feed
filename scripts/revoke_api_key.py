"""Revoke an API key.

Flips ``revoked_at = now()`` on the matching ``quake.api_keys`` row and
destroys the Vault path so the raw value is unrecoverable. Idempotent
— a second call against an already-revoked key prints a notice and
exits 0.

Operator interface lives in the makefile (``make revoke-api-key``);
this module is also import-callable so unit tests can exercise the
flow without spawning a subprocess.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import IO, Protocol

from database.etls.api_keys import ApiKeysETL
from functions.vault import VaultClient
from quake.api.auth import get_vault_client, vault_path


class _VaultDeleter(Protocol):
    """Minimal surface :func:`revoke` needs from a Vault client."""

    def delete_secret(self, path: str) -> None: ...


def revoke(
    *,
    key_id: int,
    vault: _VaultDeleter,
    stdout: IO[str] = sys.stdout,
    stderr: IO[str] = sys.stderr,
) -> int:
    """Revoke one key by id. Returns 0 on success or already-revoked, 2 on unknown id."""
    api_keys = ApiKeysETL()
    row = api_keys.get_by_id(key_id)
    if row is None:
        print(f"no such key_id: {key_id}", file=stderr)
        return 2
    if row.revoked_at is not None:
        print(f"key_id {key_id} already revoked at {row.revoked_at.isoformat()}", file=stdout)
        return 0

    api_keys.revoke(key_id)
    vault.delete_secret(vault_path(key_id))
    print(f"revoked key_id {key_id}", file=stdout)
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="make revoke-api-key",
        description="Revoke an API key by id. Flips revoked_at + destroys the Vault path.",
    )
    parser.add_argument("--key-id", type=int, required=True, help="The id from quake.api_keys.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    vault: VaultClient = get_vault_client()
    return revoke(key_id=args.key_id, vault=vault)


if __name__ == "__main__":
    raise SystemExit(main())
