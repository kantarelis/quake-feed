"""ETL for ``quake.ingestion_runs`` — per-poll observability records.

Each USGS poll opens a run with :meth:`IngestionRunsETL.start_run`, does
its work, and closes the run with :meth:`finish_run` carrying the final
insert/update/revision counts (or an ``error`` string on failure).
Grafana reads from this table to plot ingestion success and latency.
"""

from __future__ import annotations

from database.main import ExtractTransformLoad
from database.models import IngestionRunRow


class IngestionRunsETL(ExtractTransformLoad):
    """Reads and writes against ``quake.ingestion_runs``."""

    def start_run(self) -> int:
        """Open a new run and return its ``id``.

        Relies on the column defaults: ``started_at = now()`` and every count
        column defaults to ``0``. ``finished_at`` stays NULL until
        :meth:`finish_run` is called.
        """
        row = self._execute(
            "INSERT INTO quake.ingestion_runs (started_at) VALUES (now()) RETURNING id",
            fetch="one",
        )
        return int(row["id"])

    def finish_run(
        self,
        run_id: int,
        *,
        inserted: int,
        updated: int,
        revisions: int,
        error: str | None = None,
    ) -> None:
        """Close a run with its final counts. Sets ``finished_at = now()``."""
        self._execute(
            """
            UPDATE quake.ingestion_runs
               SET finished_at    = now(),
                   inserted_count = %s,
                   updated_count  = %s,
                   revision_count = %s,
                   error          = %s
             WHERE id = %s
            """,
            (inserted, updated, revisions, error, run_id),
        )

    def latest(self, limit: int) -> list[IngestionRunRow]:
        """Return the most recent ``limit`` runs, newest first."""
        rows = self._execute(
            """
            SELECT *
            FROM quake.ingestion_runs
            ORDER BY started_at DESC, id DESC
            LIMIT %s
            """,
            (limit,),
            fetch="all",
        )
        return [IngestionRunRow.model_validate(r) for r in rows]
