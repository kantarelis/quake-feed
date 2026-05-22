"""List issued API keys.

Prints id / label / scopes / timestamps / status for every row in
``quake.api_keys`` — a lookup aid for ``make revoke-api-key``, which needs an
id. The raw key is never shown: it lives only in Vault and is printed once at
issue time.

Operator interface lives in the makefile (``make list-api-keys``); this module
is also import-callable so unit tests can exercise it without a subprocess.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from typing import IO

from database.etls.api_keys import ApiKeysETL


def _fmt_dt(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value is not None else "-"


def list_keys(*, stdout: IO[str] = sys.stdout) -> int:
    """Print every API-key registration, oldest id first. Always returns 0."""
    rows = ApiKeysETL().list_all()
    if not rows:
        print("no API keys issued", file=stdout)
        return 0

    print(f"{'ID':>4}  {'LABEL':<16}  {'SCOPES':<16}  {'CREATED':<20}  {'LAST SEEN':<20}  STATUS", file=stdout)
    for row in rows:
        status = f"revoked {row.revoked_at.isoformat(timespec='seconds')}" if row.revoked_at is not None else "active"
        label = row.label or "-"
        scopes = ",".join(row.scopes) if row.scopes else "-"
        print(
            f"{row.id:>4}  {label:<16}  {scopes:<16}  "
            f"{_fmt_dt(row.created_at):<20}  {_fmt_dt(row.last_seen_at):<20}  {status}",
            file=stdout,
        )
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="make list-api-keys",
        description="List issued API keys (id, label, scopes, status). Never prints raw keys.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    _parse_args(argv if argv is not None else sys.argv[1:])
    return list_keys()


if __name__ == "__main__":
    raise SystemExit(main())
