"""Delete revoked API keys.

Hard-deletes every ``quake.api_keys`` row whose ``revoked_at`` is set, cascading
to each key's ``quake.alert_filters`` (FK ``ON DELETE CASCADE``). Their Vault
secrets were already destroyed when the key was revoked, so this is DB-only
cleanup. Active keys are never touched.

This drops the audit trail for the pruned keys — it is operator-initiated tidying,
not part of the normal revoke flow (which keeps a tombstone).

Operator interface lives in the makefile (``make prune-api-keys``); this module
is also import-callable so unit tests can exercise it without a subprocess.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import IO

from database.etls.api_keys import ApiKeysETL


def prune(*, stdout: IO[str] = sys.stdout) -> int:
    """Delete all revoked keys. Prints how many were removed; always returns 0."""
    removed = ApiKeysETL().delete_revoked()
    if removed == 0:
        print("no revoked keys to prune", file=stdout)
    else:
        print(f"pruned {removed} revoked key(s)", file=stdout)
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="make prune-api-keys",
        description="Hard-delete all revoked API keys (cascades to their alert filters). Active keys untouched.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    _parse_args(argv if argv is not None else sys.argv[1:])
    return prune()


if __name__ == "__main__":
    raise SystemExit(main())
