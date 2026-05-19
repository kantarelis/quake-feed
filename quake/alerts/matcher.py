"""Decide whether one event matches one filter row.

Pure function — no I/O, no DB, no side effects. Called by
:class:`quake.alerts.registry.SubscriberRegistry` (Task 3) on every
event for every active subscriber.

Composition rules (locked in PLAN.md):

* **AND within one filter.** Every *set* predicate on the filter row
  must hold for the event to match. A predicate is "set" when its
  columns on :class:`database.models.AlertFilterRow` are non-NULL —
  a NULL column means *the operator did not constrain this dimension,
  so skip it*.
* **OR across a key's filters** is the registry's job (Task 3); this
  module deals with one filter at a time.

Predicates currently supported:

* ``min_magnitude`` — ``event.magnitude >= filter.min_magnitude``.
* Bbox — ``event.latitude / longitude`` inside the inclusive
  ``bbox_min_*`` / ``bbox_max_*`` rectangle.
* Center+radius — great-circle distance (haversine) from
  ``(center_lat, center_lon)`` to the event is at most ``radius_km``.

A bbox that spans the antimeridian (``bbox_min_lon > bbox_max_lon``)
isn't supported in V1 — the :class:`models.alerts.AlertFilter`
validator rejects such inputs at the API layer, so the matcher can
safely assume ordered bounds.
"""

from __future__ import annotations

import math

from database.models import AlertFilterRow, EventRow

_EARTH_RADIUS_KM = 6371.0


def matches(filter_row: AlertFilterRow, event: EventRow) -> bool:
    """Return whether ``event`` satisfies every set predicate on ``filter_row``."""
    if filter_row.min_magnitude is not None and event.magnitude < filter_row.min_magnitude:
        return False

    bbox = _bbox_bounds(filter_row)
    if bbox is not None and not _inside_bbox(bbox, event):
        return False

    center = _center_bounds(filter_row)
    if center is not None and not _inside_radius(center, event):
        return False

    return True


def _bbox_bounds(f: AlertFilterRow) -> tuple[float, float, float, float] | None:
    """Return ``(min_lat, min_lon, max_lat, max_lon)`` if bbox is fully set, else ``None``."""
    if f.bbox_min_lat is None or f.bbox_min_lon is None or f.bbox_max_lat is None or f.bbox_max_lon is None:
        return None
    return f.bbox_min_lat, f.bbox_min_lon, f.bbox_max_lat, f.bbox_max_lon


def _center_bounds(f: AlertFilterRow) -> tuple[float, float, float] | None:
    """Return ``(center_lat, center_lon, radius_km)`` if center+radius is set, else ``None``."""
    if f.center_lat is None or f.center_lon is None or f.radius_km is None:
        return None
    return f.center_lat, f.center_lon, f.radius_km


def _inside_bbox(bbox: tuple[float, float, float, float], event: EventRow) -> bool:
    min_lat, min_lon, max_lat, max_lon = bbox
    return min_lat <= event.latitude <= max_lat and min_lon <= event.longitude <= max_lon


def _inside_radius(center: tuple[float, float, float], event: EventRow) -> bool:
    center_lat, center_lon, radius_km = center
    distance = _haversine_km(center_lat, center_lon, event.latitude, event.longitude)
    return distance <= radius_km


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two ``(lat, lon)`` points."""
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))
