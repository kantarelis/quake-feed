"""Parse a USGS GeoJSON FeatureCollection into ``EventRow`` batches.

Pure transform — no I/O, no DB. Features missing any required field are
skipped with a warning log rather than failing the entire batch (USGS
occasionally emits oddly-shaped records, and one bad feature shouldn't
cost us the other 29).

The :func:`parse_feed` function is the only public API.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database.models import EventRow
from functions.logger import setup_logger

logger = setup_logger("usgs-parser", "quake-feed")


def parse_feed(geojson: dict[str, Any]) -> list[EventRow]:
    """Convert a USGS FeatureCollection into a list of :class:`EventRow`.

    Missing-field handling: any Feature lacking ``id``, ``properties.time``,
    ``properties.mag``, or the ``geometry.coordinates`` longitude/latitude
    pair is skipped with a WARNING log line. The rest of the batch is
    returned. ``depth_km`` (coordinate index 2) is allowed to be absent —
    it's a nullable column.

    ``inserted_at`` / ``updated_at`` are populated with the current UTC
    time as a placeholder; the DB's ``DEFAULT now()`` overrides them on
    actual INSERT, so the parser-assigned values are throwaway.
    """
    features = geojson.get("features", [])
    now = datetime.now(timezone.utc)
    rows: list[EventRow] = []
    for feature in features:
        row = _feature_to_row(feature, now=now)
        if row is not None:
            rows.append(row)
    return rows


def _feature_to_row(feature: dict[str, Any], *, now: datetime) -> EventRow | None:
    """Map one USGS Feature → ``EventRow``, or ``None`` if a required field is missing."""
    event_id = feature.get("id")
    props = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []

    time_ms = props.get("time")
    magnitude = props.get("mag")

    if event_id is None or time_ms is None or magnitude is None or len(coords) < 2:
        logger.warning(
            "Skipping malformed USGS feature",
            extra={
                "event_id": event_id,
                "has_time": time_ms is not None,
                "has_mag": magnitude is not None,
                "coord_len": len(coords),
            },
        )
        return None

    longitude = coords[0]
    latitude = coords[1]
    depth_km = coords[2] if len(coords) >= 3 else None

    return EventRow(
        event_id=event_id,
        time=datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc),
        magnitude=magnitude,
        magnitude_type=props.get("magType"),
        depth_km=depth_km,
        latitude=latitude,
        longitude=longitude,
        place=props.get("place"),
        status=props.get("status"),
        tsunami=bool(props.get("tsunami", 0)),
        url=props.get("url"),
        inserted_at=now,
        updated_at=now,
    )
