"""ETL for ``quake.api_keys``.

Hash-in / hash-out. The raw API key never appears in this layer — hashing
happens in the issuance flow (Epic 5) before the hash reaches ``insert``.
"""

from __future__ import annotations

from database.main import ExtractTransformLoad
from database.models import ApiKeyRow


class ApiKeysETL(ExtractTransformLoad):
    """Reads and writes against ``quake.api_keys``."""

    def insert(self, key_hash: str, label: str | None, scopes: list[str]) -> int:
        """Persist a new key registration and return its ``id``."""
        row = self._execute(
            """
            INSERT INTO quake.api_keys (key_hash, label, scopes)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (key_hash, label, scopes),
            fetch="one",
        )
        return int(row["id"])

    def get_by_hash(self, key_hash: str) -> ApiKeyRow | None:
        """Return the row whose ``key_hash`` matches, or ``None`` on miss."""
        row = self._execute(
            "SELECT * FROM quake.api_keys WHERE key_hash = %s",
            (key_hash,),
            fetch="one",
        )
        return ApiKeyRow.model_validate(row) if row is not None else None

    def get_by_id(self, api_key_id: int) -> ApiKeyRow | None:
        """Return the row with this ``id``, or ``None`` on miss."""
        row = self._execute(
            "SELECT * FROM quake.api_keys WHERE id = %s",
            (api_key_id,),
            fetch="one",
        )
        return ApiKeyRow.model_validate(row) if row is not None else None

    def delete(self, api_key_id: int) -> None:
        """Hard-delete a row.

        Used only by the issuance rollback path when the Vault put fails —
        the row was never functional, so leaving a revoked tombstone would
        be misleading. Operator-initiated takedowns use :meth:`revoke`.
        """
        self._execute(
            "DELETE FROM quake.api_keys WHERE id = %s",
            (api_key_id,),
        )

    def touch_last_seen(self, api_key_id: int) -> None:
        """Stamp ``last_seen_at = now()`` for the given key."""
        self._execute(
            "UPDATE quake.api_keys SET last_seen_at = now() WHERE id = %s",
            (api_key_id,),
        )

    def revoke(self, api_key_id: int) -> None:
        """Mark a key revoked with ``revoked_at = now()``.

        Idempotent: only updates rows where ``revoked_at IS NULL``, so a
        second call against an already-revoked key preserves the original
        revocation timestamp.
        """
        self._execute(
            "UPDATE quake.api_keys SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL",
            (api_key_id,),
        )
