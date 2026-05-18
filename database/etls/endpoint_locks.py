"""ETL for ``quake.endpoint_locks`` — runtime kill-switch flags.

Lock rows are seeded by the baseline migration; no other code path
creates them at runtime. ``set_lock`` / ``clear_lock`` return ``None``
on an unknown name so the caller (typically the ``/admin/locks`` view
layer in Task 5) can translate that to a 404 cleanly.

``is_locked`` fails open — an unknown name returns ``False``. The
practical semantics: every lock the application actually cares about
exists in the table because the migration created it. A missing row
means "code bug, not operator state"; the ingestion path would rather
keep running than silently halt on a typo.
"""

from __future__ import annotations

from database.main import ExtractTransformLoad
from database.models import EndpointLockRow


class EndpointLocksETL(ExtractTransformLoad):
    """Reads and writes against ``quake.endpoint_locks``."""

    def list_all(self) -> list[EndpointLockRow]:
        rows = self._execute(
            "SELECT * FROM quake.endpoint_locks ORDER BY lock_name",
            fetch="all",
        )
        return [EndpointLockRow.model_validate(r) for r in rows]

    def is_locked(self, lock_name: str) -> bool:
        row = self._execute(
            "SELECT is_locked FROM quake.endpoint_locks WHERE lock_name = %s",
            (lock_name,),
            fetch="one",
        )
        return bool(row["is_locked"]) if row is not None else False

    def set_lock(
        self,
        lock_name: str,
        *,
        locked_by: str | None,
        reason: str | None,
    ) -> EndpointLockRow | None:
        """Set ``is_locked = true`` on an existing lock. Returns ``None`` if no such name."""
        row = self._execute(
            """
            UPDATE quake.endpoint_locks
               SET is_locked = true,
                   locked_by = %s,
                   locked_at = now(),
                   reason    = %s
             WHERE lock_name = %s
            RETURNING *
            """,
            (locked_by, reason, lock_name),
            fetch="one",
        )
        return EndpointLockRow.model_validate(row) if row is not None else None

    def clear_lock(self, lock_name: str) -> EndpointLockRow | None:
        """Reset ``is_locked = false`` and clear the metadata columns. ``None`` if no such name."""
        row = self._execute(
            """
            UPDATE quake.endpoint_locks
               SET is_locked = false,
                   locked_by = NULL,
                   locked_at = NULL,
                   reason    = NULL
             WHERE lock_name = %s
            RETURNING *
            """,
            (lock_name,),
            fetch="one",
        )
        return EndpointLockRow.model_validate(row) if row is not None else None
