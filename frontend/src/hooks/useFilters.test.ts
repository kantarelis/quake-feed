import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useFilters } from "./useFilters";

const { apiRequestMock } = vi.hoisted(() => ({ apiRequestMock: vi.fn() }));

vi.mock("../api/client", () => ({
  apiRequest: apiRequestMock,
}));

const FILTER = {
  id: 1,
  api_key_id: 1,
  min_magnitude: 4,
  created_at: "2026-05-21T00:00:00Z",
  updated_at: "2026-05-21T00:00:00Z",
};

beforeEach(() => {
  apiRequestMock.mockReset();
});

describe("useFilters", () => {
  it("loads filters on mount", async () => {
    apiRequestMock.mockResolvedValue({ count: 1, filters: [FILTER] });

    const { result } = renderHook(() => useFilters());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.filters).toEqual([FILTER]);
    expect(apiRequestMock).toHaveBeenCalledWith(
      "/alerts/filters",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("surfaces a load error", async () => {
    apiRequestMock.mockRejectedValue(new Error("API key missing or invalid"));

    const { result } = renderHook(() => useFilters());

    await waitFor(() => expect(result.current.error).toBe("API key missing or invalid"));
    expect(result.current.filters).toEqual([]);
  });

  it("POSTs a new filter then reloads the list", async () => {
    apiRequestMock
      .mockResolvedValueOnce({ count: 0, filters: [] }) // initial load
      .mockResolvedValueOnce(FILTER) // POST
      .mockResolvedValueOnce({ count: 1, filters: [FILTER] }); // reload

    const { result } = renderHook(() => useFilters());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.create({ min_magnitude: 4 });
    });

    expect(apiRequestMock).toHaveBeenNthCalledWith(2, "/alerts/filters", {
      method: "POST",
      json: { min_magnitude: 4 },
    });
    await waitFor(() => expect(result.current.filters).toEqual([FILTER]));
  });

  it("DELETEs a filter then reloads the list", async () => {
    apiRequestMock
      .mockResolvedValueOnce({ count: 1, filters: [FILTER] }) // initial load
      .mockResolvedValueOnce(undefined) // DELETE
      .mockResolvedValueOnce({ count: 0, filters: [] }); // reload

    const { result } = renderHook(() => useFilters());
    await waitFor(() => expect(result.current.filters).toEqual([FILTER]));

    await act(async () => {
      await result.current.remove(1);
    });

    expect(apiRequestMock).toHaveBeenNthCalledWith(2, "/alerts/filters/1", { method: "DELETE" });
    await waitFor(() => expect(result.current.filters).toEqual([]));
  });

  it("re-throws so the caller can surface a 422", async () => {
    apiRequestMock
      .mockResolvedValueOnce({ count: 0, filters: [] })
      .mockRejectedValueOnce(new Error("empty filter"));

    const { result } = renderHook(() => useFilters());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await expect(result.current.create({})).rejects.toThrow("empty filter");
  });
});
