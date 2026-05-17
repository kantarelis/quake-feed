"""Read-only ETL for ``quake.event_revisions``.

Rows are produced exclusively by the ``events_revision_trigger`` defined
in the baseline migration. There are no write methods here — any insert
path would silently bypass the trigger's threshold logic and corrupt the
audit log.
"""

from __future__ import annotations

from database.main import ExtractTransformLoad
from database.models import EventRevisionRow


class RevisionsETL(ExtractTransformLoad):
    """Reads against ``quake.event_revisions``."""

    def for_event(self, event_id: str) -> list[EventRevisionRow]:
        """Return every revision recorded for ``event_id``, newest first."""
        rows = self._execute(
            """
            SELECT *
            FROM quake.event_revisions
            WHERE event_id = %s
            ORDER BY observed_at DESC, id DESC
            """,
            (event_id,),
            fetch="all",
        )
        return [EventRevisionRow.model_validate(r) for r in rows]

    def recent(self, limit: int) -> list[EventRevisionRow]:
        """Return the most recent ``limit`` revisions across all events."""
        rows = self._execute(
            """
            SELECT *
            FROM quake.event_revisions
            ORDER BY observed_at DESC, id DESC
            LIMIT %s
            """,
            (limit,),
            fetch="all",
        )
        return [EventRevisionRow.model_validate(r) for r in rows]
