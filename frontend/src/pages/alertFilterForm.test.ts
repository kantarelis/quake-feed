import { describe, expect, it } from "vitest";

import { buildFilter, describeFilter, EMPTY_FORM, type FilterFormState } from "./alertFilterForm";

function form(overrides: Partial<FilterFormState>): FilterFormState {
  return { ...EMPTY_FORM, ...overrides };
}

describe("buildFilter", () => {
  it("rejects an empty filter", () => {
    const result = buildFilter(EMPTY_FORM);
    expect(result).toEqual({ ok: false, error: expect.stringContaining("minimum magnitude") });
  });

  it("accepts magnitude only", () => {
    expect(buildFilter(form({ minMagnitude: "4.5" }))).toEqual({
      ok: true,
      body: { min_magnitude: 4.5 },
    });
  });

  it("rejects a non-numeric magnitude", () => {
    const result = buildFilter(form({ minMagnitude: "big" }));
    expect(result.ok).toBe(false);
  });

  it("rejects a magnitude out of range", () => {
    const result = buildFilter(form({ minMagnitude: "11" }));
    expect(result).toEqual({ ok: false, error: expect.stringContaining("between -1 and 10") });
  });

  it("rejects a partial bounding box", () => {
    const result = buildFilter(form({ shape: "bbox", bboxMinLat: "10", bboxMinLon: "10" }));
    expect(result).toEqual({ ok: false, error: expect.stringContaining("all four") });
  });

  it("rejects a bounding box with an out-of-range latitude", () => {
    const result = buildFilter(
      form({
        shape: "bbox",
        bboxMinLat: "100",
        bboxMinLon: "0",
        bboxMaxLat: "20",
        bboxMaxLon: "20",
      }),
    );
    expect(result).toEqual({ ok: false, error: expect.stringContaining("Min latitude") });
  });

  it("rejects an inverted bounding box", () => {
    const result = buildFilter(
      form({
        shape: "bbox",
        bboxMinLat: "30",
        bboxMinLon: "0",
        bboxMaxLat: "20",
        bboxMaxLon: "20",
      }),
    );
    expect(result).toEqual({ ok: false, error: expect.stringContaining("≤ max latitude") });
  });

  it("accepts a valid bounding box combined with magnitude", () => {
    expect(
      buildFilter(
        form({
          minMagnitude: "3",
          shape: "bbox",
          bboxMinLat: "10",
          bboxMinLon: "20",
          bboxMaxLat: "30",
          bboxMaxLon: "40",
        }),
      ),
    ).toEqual({
      ok: true,
      body: {
        min_magnitude: 3,
        bbox_min_lat: 10,
        bbox_min_lon: 20,
        bbox_max_lat: 30,
        bbox_max_lon: 40,
      },
    });
  });

  it("rejects a partial center+radius", () => {
    const result = buildFilter(form({ shape: "center", centerLat: "10" }));
    expect(result).toEqual({
      ok: false,
      error: expect.stringContaining("Center + radius requires"),
    });
  });

  it("rejects a non-positive radius", () => {
    const result = buildFilter(
      form({ shape: "center", centerLat: "10", centerLon: "20", radiusKm: "0" }),
    );
    expect(result).toEqual({ ok: false, error: expect.stringContaining("between 0 and 20000") });
  });

  it("accepts a valid center+radius", () => {
    expect(
      buildFilter(form({ shape: "center", centerLat: "37.9", centerLon: "23.7", radiusKm: "250" })),
    ).toEqual({
      ok: true,
      body: { center_lat: 37.9, center_lon: 23.7, radius_km: 250 },
    });
  });
});

describe("describeFilter", () => {
  it("summarizes magnitude and a bounding box", () => {
    const text = describeFilter({
      id: 1,
      api_key_id: 1,
      min_magnitude: 4,
      bbox_min_lat: 10,
      bbox_min_lon: 20,
      bbox_max_lat: 30,
      bbox_max_lon: 40,
      created_at: "2026-05-21T00:00:00Z",
      updated_at: "2026-05-21T00:00:00Z",
    });
    expect(text).toContain("M ≥ 4");
    expect(text).toContain("bbox");
  });

  it("summarizes a center+radius", () => {
    const text = describeFilter({
      id: 2,
      api_key_id: 1,
      center_lat: 37.9,
      center_lon: 23.7,
      radius_km: 250,
      created_at: "2026-05-21T00:00:00Z",
      updated_at: "2026-05-21T00:00:00Z",
    });
    expect(text).toContain("within 250 km");
  });
});
