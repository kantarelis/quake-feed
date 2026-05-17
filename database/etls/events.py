"""ETL for ``quake.events``.

Owns every read/write against the events hypertable. Revisions are *not*
written here — they're produced by the ``events_revision_trigger`` defined
in the baseline migration whenever an UPDATE crosses a noise threshold.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from database.main import ExtractTransformLoad, transaction
from database.models import EventRow

UpsertOutcome = Literal["inserted", "updated"]

_UPSERT_SQL = """
    INSERT INTO quake.events (
        event_id, time, magnitude, magnitude_type, depth_km,
        latitude, longitude, place, status, tsunami, url
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (event_id, time) DO UPDATE SET
        magnitude      = EXCLUDED.magnitude,
        magnitude_type = EXCLUDED.magnitude_type,
        depth_km       = EXCLUDED.depth_km,
        latitude       = EXCLUDED.latitude,
        longitude      = EXCLUDED.longitude,
        place          = EXCLUDED.place,
        status         = EXCLUDED.status,
        tsunami        = EXCLUDED.tsunami,
        url            = EXCLUDED.url,
        updated_at     = now()
    RETURNING (xmax = 0) AS was_insert
"""


def _row_to_params(event: EventRow) -> tuple[
    str,
    datetime,
    float,
    str | None,
    float | None,
    float,
    float,
    str | None,
    str | None,
    bool,
    str | None,
]:
    return (
        event.event_id,
        event.time,
        event.magnitude,
        event.magnitude_type,
        event.depth_km,
        event.latitude,
        event.longitude,
        event.place,
        event.status,
        event.tsunami,
        event.url,
    )


class EventsETL(ExtractTransformLoad):
    """Reads and writes against ``quake.events``."""

    def upsert(self, event: EventRow) -> UpsertOutcome:
        """Insert or update one row. Returns ``"inserted"`` or ``"updated"``.

        ``xmax = 0`` on the returned row distinguishes a fresh insert (xmax
        is the deleting-transaction id, which is 0 for an unmodified row)
        from a conflict-driven UPDATE.

        The plan left ``"unchanged"`` as an option — not implemented. An
        UPSERT that lands on an existing key always runs the UPDATE, even
        if every column would be the same. The revision trigger handles the
        "did anything actually change" question for the audit log; this
        method only reports insert vs. update.
        """
        row = self._execute(_UPSERT_SQL, _row_to_params(event), fetch="one")
        return "inserted" if row["was_insert"] else "updated"

    def upsert_many(self, events: Iterable[EventRow]) -> dict[str, int]:
        """Batched upsert in a single transaction. Returns insert/update counts."""
        counts = {"inserted": 0, "updated": 0}
        with transaction() as conn:
            with conn.cursor() as cur:
                for event in events:
                    cur.execute(_UPSERT_SQL, _row_to_params(event))
                    result = cur.fetchone()
                    if result is None:
                        continue
                    (was_insert,) = result
                    counts["inserted" if was_insert else "updated"] += 1
        return counts

    def get_by_id(self, event_id: str) -> EventRow | None:
        """Return the freshest row for ``event_id`` (largest ``time``)."""
        row = self._execute(
            """
            SELECT *
            FROM quake.events
            WHERE event_id = %s
            ORDER BY time DESC
            LIMIT 1
            """,
            (event_id,),
            fetch="one",
        )
        return EventRow.model_validate(row) if row is not None else None

    def recent(self, limit: int) -> list[EventRow]:
        """Return the most recent ``limit`` events, newest first."""
        rows = self._execute(
            "SELECT * FROM quake.events ORDER BY time DESC LIMIT %s",
            (limit,),
            fetch="all",
        )
        return [EventRow.model_validate(r) for r in rows]

    def by_magnitude(self, min_magnitude: float, since: datetime | None = None) -> list[EventRow]:
        """Return events with ``magnitude >= min_magnitude``, optionally bounded by ``time >= since``."""
        rows = self._execute(
            """
            SELECT *
            FROM quake.events
            WHERE magnitude >= %s
              AND (%s::timestamptz IS NULL OR time >= %s::timestamptz)
            ORDER BY time DESC
            """,
            (min_magnitude, since, since),
            fetch="all",
        )
        return [EventRow.model_validate(r) for r in rows]

    def near(self, lat: float, lon: float, radius_km: float) -> list[EventRow]:
        """Return events within ``radius_km`` of ``(lat, lon)``.

        Two-step: a fast bounding-box pre-filter on the ``(latitude, longitude)``
        index, then a haversine distance check inline in SQL. The bounding-box
        deltas are derived from 1° ≈ 111 km; longitude is corrected for the
        latitude's cosine, clamped to avoid a divide-by-zero at the poles.
        """
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 1e-4))
        rows = self._execute(
            """
            SELECT *
            FROM quake.events
            WHERE latitude  BETWEEN %s AND %s
              AND longitude BETWEEN %s AND %s
              AND 2 * 6371 * asin(sqrt(
                    power(sin(radians((latitude - %s) / 2)), 2)
                    + cos(radians(%s)) * cos(radians(latitude))
                    * power(sin(radians((longitude - %s) / 2)), 2)
                  )) <= %s
            ORDER BY time DESC
            """,
            (lat - dlat, lat + dlat, lon - dlon, lon + dlon, lat, lat, lon, radius_km),
            fetch="all",
        )
        return [EventRow.model_validate(r) for r in rows]
