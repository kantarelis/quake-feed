"""ETL for ``quake.alert_filters``.

CRUD against the per-API-key filter table. Writes are deliberately split
into ``insert`` / ``update`` rather than a single ``upsert(row)`` — the
table auto-assigns ``id`` and ``created_at``/``updated_at``, so callers
can't supply an ``AlertFilterRow`` (a *read* shape) when creating a brand-
new filter. ``insert`` / ``update`` mirror the API layer's POST / PATCH
operations directly.

The filter shape (bbox XOR center+radius) is enforced application-side;
this layer accepts both column sets and the matcher decides per row.
``update`` and ``delete`` both scope on ``api_key_id`` in their WHERE
clauses as a defence against cross-key access.
"""

from __future__ import annotations

from database.main import ExtractTransformLoad
from database.models import AlertFilterRow


class AlertFiltersETL(ExtractTransformLoad):
    """Reads and writes against ``quake.alert_filters``."""

    def insert(
        self,
        api_key_id: int,
        *,
        min_magnitude: float | None = None,
        bbox_min_lat: float | None = None,
        bbox_min_lon: float | None = None,
        bbox_max_lat: float | None = None,
        bbox_max_lon: float | None = None,
        center_lat: float | None = None,
        center_lon: float | None = None,
        radius_km: float | None = None,
    ) -> int:
        """Create a new filter row and return its assigned ``id``."""
        row = self._execute(
            """
            INSERT INTO quake.alert_filters (
                api_key_id, min_magnitude,
                bbox_min_lat, bbox_min_lon, bbox_max_lat, bbox_max_lon,
                center_lat, center_lon, radius_km
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                api_key_id,
                min_magnitude,
                bbox_min_lat,
                bbox_min_lon,
                bbox_max_lat,
                bbox_max_lon,
                center_lat,
                center_lon,
                radius_km,
            ),
            fetch="one",
        )
        return int(row["id"])

    def update(
        self,
        filter_id: int,
        api_key_id: int,
        *,
        min_magnitude: float | None = None,
        bbox_min_lat: float | None = None,
        bbox_min_lon: float | None = None,
        bbox_max_lat: float | None = None,
        bbox_max_lon: float | None = None,
        center_lat: float | None = None,
        center_lon: float | None = None,
        radius_km: float | None = None,
    ) -> bool:
        """Full-replacement update of a filter's fields. Returns whether a row was updated.

        ``api_key_id`` is included in the WHERE clause as a cross-key defence —
        an update keyed only on ``filter_id`` would let a misbehaving caller
        modify another key's filters by guessing ids.
        """
        row = self._execute(
            """
            UPDATE quake.alert_filters
               SET min_magnitude = %s,
                   bbox_min_lat  = %s,
                   bbox_min_lon  = %s,
                   bbox_max_lat  = %s,
                   bbox_max_lon  = %s,
                   center_lat    = %s,
                   center_lon    = %s,
                   radius_km     = %s,
                   updated_at    = now()
             WHERE id = %s AND api_key_id = %s
            RETURNING 1
            """,
            (
                min_magnitude,
                bbox_min_lat,
                bbox_min_lon,
                bbox_max_lat,
                bbox_max_lon,
                center_lat,
                center_lon,
                radius_km,
                filter_id,
                api_key_id,
            ),
            fetch="one",
        )
        return row is not None

    def for_api_key(self, api_key_id: int) -> list[AlertFilterRow]:
        """Return every filter owned by the given API key, ordered by id."""
        rows = self._execute(
            "SELECT * FROM quake.alert_filters WHERE api_key_id = %s ORDER BY id",
            (api_key_id,),
            fetch="all",
        )
        return [AlertFilterRow.model_validate(r) for r in rows]

    def delete(self, filter_id: int, api_key_id: int) -> bool:
        """Delete a filter scoped to its owning API key. Returns whether a row was removed."""
        row = self._execute(
            """
            DELETE FROM quake.alert_filters
             WHERE id = %s AND api_key_id = %s
            RETURNING 1
            """,
            (filter_id, api_key_id),
            fetch="one",
        )
        return row is not None
