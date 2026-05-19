"""Issue a fresh API key.

Generates a ``qkf_<hex32>`` value, persists its SHA-256 hash in
``quake.api_keys``, stores the raw value in Vault at
``secret/api-keys/<id>``, and prints the raw key to stdout exactly
once. The raw value is never written to a log line, metric, or
audit row.

Operator interface lives in the makefile (``make issue-api-key``);
this module is also import-callable so unit tests can exercise the
flow without spawning a subprocess.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import IO, Protocol

from database.etls.api_keys import ApiKeysETL
from functions.vault import VaultClient
from quake.api.auth import generate_raw_key, get_vault_client, hash_key, vault_path


class _VaultWriter(Protocol):
    """Minimal surface :func:`issue` needs from a Vault client."""

    def put_secret(self, path: str, payload: dict[str, str]) -> None: ...


def issue(
    *,
    label: str | None,
    scopes: list[str],
    vault: _VaultWriter,
    stdout: IO[str] = sys.stdout,
) -> int:
    """Issue one key and return its ``key_id``.

    Inserts the DB row first; if the Vault put fails we hard-delete the
    row so a half-issued key never lingers. (A revoked tombstone would
    misrepresent a key that was never functional.)
    """
    raw = generate_raw_key()
    api_keys = ApiKeysETL()
    key_id = api_keys.insert(key_hash=hash_key(raw), label=label, scopes=scopes)
    try:
        vault.put_secret(
            vault_path(key_id),
            {
                "raw_key": raw,
                "label": label or "",
                "issued_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception:
        api_keys.delete(key_id)
        raise

    print(f"key_id   : {key_id}", file=stdout)
    print(f"label    : {label or '(none)'}", file=stdout)
    print(f"scopes   : {','.join(scopes) if scopes else '(none)'}", file=stdout)
    print("", file=stdout)
    print("Raw API key (save this — it cannot be recovered):", file=stdout)
    print(raw, file=stdout)
    return key_id


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="make issue-api-key",
        description="Issue a new API key. Writes the hash to quake.api_keys and the raw value to Vault.",
    )
    parser.add_argument("--label", default=None, help="Operator-supplied tag (optional).")
    parser.add_argument(
        "--scopes",
        default="",
        help="Comma-separated scopes (e.g. 'admin' or 'admin,read'). Empty means no scopes.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    vault: VaultClient = get_vault_client()
    issue(label=args.label, scopes=scopes, vault=vault)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
