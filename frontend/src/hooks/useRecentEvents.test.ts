import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRecentEvents } from "./useRecentEvents";

const { apiRequestMock } = vi.hoisted(() => ({ apiRequestMock: vi.fn() }));

vi.mock("../api/client", () => ({
  apiRequest: apiRequestMock,
}));

const SAMPLE = {
  event_id: "us1",
  time: "2026-05-21T10:00:00Z",
  magnitude: 5.2,
  latitude: 1,
  longitude: 2,
  tsunami: false,
};

beforeEach(() => {
  apiRequestMock.mockReset();
});

describe("useRecentEvents", () => {
  it("loads events on mount and clears loading", async () => {
    apiRequestMock.mockResolvedValue({ count: 1, events: [SAMPLE] });

    const { result } = renderHook(() => useRecentEvents({ intervalMs: 0 }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.events).toEqual([SAMPLE]);
    expect(result.current.error).toBeNull();
  });

  it("requests the configured limit", async () => {
    apiRequestMock.mockResolvedValue({ count: 0, events: [] });

    renderHook(() => useRecentEvents({ limit: 25, intervalMs: 0 }));

    await waitFor(() => expect(apiRequestMock).toHaveBeenCalled());
    expect(apiRequestMock).toHaveBeenCalledWith(
      "/events/recent?limit=25",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("resolves to an empty list", async () => {
    apiRequestMock.mockResolvedValue({ count: 0, events: [] });

    const { result } = renderHook(() => useRecentEvents({ intervalMs: 0 }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.events).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it("surfaces the normalized error message on failure", async () => {
    apiRequestMock.mockRejectedValue(new Error("API key missing or invalid"));

    const { result } = renderHook(() => useRecentEvents({ intervalMs: 0 }));

    await waitFor(() => expect(result.current.error).toBe("API key missing or invalid"));
    expect(result.current.events).toEqual([]);
    expect(result.current.loading).toBe(false);
  });

  it("refetches when refresh is called", async () => {
    apiRequestMock.mockResolvedValue({ count: 0, events: [] });

    const { result } = renderHook(() => useRecentEvents({ intervalMs: 0 }));
    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(1));

    act(() => {
      result.current.refresh();
    });

    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(2));
  });
});
