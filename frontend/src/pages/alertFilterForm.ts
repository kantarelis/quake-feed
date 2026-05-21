// Pure form helpers for the alert-config view, kept out of the component file
// so the validation matrix can be unit-tested directly. The rules here mirror
// the backend `AlertFilter` model validator (models/alerts.py): bbox XOR
// center+radius, optional min_magnitude, no empty filter, ranges, bbox ordering.
import type { Schemas } from "../api/client";

export type FilterShape = "none" | "bbox" | "center";

export interface FilterFormState {
  minMagnitude: string;
  shape: FilterShape;
  bboxMinLat: string;
  bboxMinLon: string;
  bboxMaxLat: string;
  bboxMaxLon: string;
  centerLat: string;
  centerLon: string;
  radiusKm: string;
}

export const EMPTY_FORM: FilterFormState = {
  minMagnitude: "",
  shape: "none",
  bboxMinLat: "",
  bboxMinLon: "",
  bboxMaxLat: "",
  bboxMaxLon: "",
  centerLat: "",
  centerLon: "",
  radiusKm: "",
};

export type BuildResult = { ok: true; body: Schemas["AlertFilter"] } | { ok: false; error: string };

/** Parse a trimmed field: blank → null, non-numeric → NaN, else the number. */
function num(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") {
    return null;
  }
  return Number(trimmed);
}

function latError(value: number, label: string): string | null {
  if (Number.isNaN(value)) {
    return `${label} must be a number.`;
  }
  if (value < -90 || value > 90) {
    return `${label} must be between -90 and 90.`;
  }
  return null;
}

function lonError(value: number, label: string): string | null {
  if (Number.isNaN(value)) {
    return `${label} must be a number.`;
  }
  if (value < -180 || value > 180) {
    return `${label} must be between -180 and 180.`;
  }
  return null;
}

/**
 * Validate the form and produce an `AlertFilter` request body, or an error
 * message ready to show the user. Only the fields for the chosen shape are
 * sent (the backend forbids extras), so bbox/center are mutually exclusive by
 * construction.
 */
export function buildFilter(form: FilterFormState): BuildResult {
  const body: Schemas["AlertFilter"] = {};

  const magnitude = num(form.minMagnitude);
  if (magnitude !== null) {
    if (Number.isNaN(magnitude)) {
      return { ok: false, error: "Minimum magnitude must be a number." };
    }
    if (magnitude < -1 || magnitude > 10) {
      return { ok: false, error: "Minimum magnitude must be between -1 and 10." };
    }
    body.min_magnitude = magnitude;
  }

  if (form.shape === "bbox") {
    const minLat = num(form.bboxMinLat);
    const minLon = num(form.bboxMinLon);
    const maxLat = num(form.bboxMaxLat);
    const maxLon = num(form.bboxMaxLon);
    if (minLat === null || minLon === null || maxLat === null || maxLon === null) {
      return { ok: false, error: "Bounding box requires all four corner values." };
    }
    const rangeError =
      latError(minLat, "Min latitude") ??
      latError(maxLat, "Max latitude") ??
      lonError(minLon, "Min longitude") ??
      lonError(maxLon, "Max longitude");
    if (rangeError) {
      return { ok: false, error: rangeError };
    }
    if (minLat > maxLat) {
      return { ok: false, error: "Min latitude must be ≤ max latitude." };
    }
    if (minLon > maxLon) {
      return { ok: false, error: "Min longitude must be ≤ max longitude." };
    }
    body.bbox_min_lat = minLat;
    body.bbox_min_lon = minLon;
    body.bbox_max_lat = maxLat;
    body.bbox_max_lon = maxLon;
  } else if (form.shape === "center") {
    const centerLat = num(form.centerLat);
    const centerLon = num(form.centerLon);
    const radiusKm = num(form.radiusKm);
    if (centerLat === null || centerLon === null || radiusKm === null) {
      return { ok: false, error: "Center + radius requires latitude, longitude and radius." };
    }
    const rangeError =
      latError(centerLat, "Center latitude") ?? lonError(centerLon, "Center longitude");
    if (rangeError) {
      return { ok: false, error: rangeError };
    }
    if (Number.isNaN(radiusKm)) {
      return { ok: false, error: "Radius must be a number." };
    }
    if (radiusKm <= 0 || radiusKm > 20_000) {
      return { ok: false, error: "Radius must be between 0 and 20000 km." };
    }
    body.center_lat = centerLat;
    body.center_lon = centerLon;
    body.radius_km = radiusKm;
  }

  if (body.min_magnitude === undefined && form.shape === "none") {
    return { ok: false, error: "Set a minimum magnitude or choose a geographic shape." };
  }

  return { ok: true, body };
}

/** One-line human description of a persisted filter, for the list rows. */
export function describeFilter(filter: Schemas["AlertFilterResponse"]): string {
  const parts: string[] = [];

  if (filter.min_magnitude != null) {
    parts.push(`M ≥ ${filter.min_magnitude}`);
  }
  if (
    filter.bbox_min_lat != null &&
    filter.bbox_min_lon != null &&
    filter.bbox_max_lat != null &&
    filter.bbox_max_lon != null
  ) {
    parts.push(
      `bbox [${filter.bbox_min_lat}, ${filter.bbox_min_lon}] → [${filter.bbox_max_lat}, ${filter.bbox_max_lon}]`,
    );
  }
  if (filter.center_lat != null && filter.center_lon != null && filter.radius_km != null) {
    parts.push(`within ${filter.radius_km} km of (${filter.center_lat}, ${filter.center_lon})`);
  }

  return parts.length > 0 ? parts.join(" · ") : "matches all events";
}
