import type { EventSourceMessage, FetchEventSourceInit } from "@microsoft/fetch-event-source";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setApiKey } from "../api/keyStore";
import { ApiKeyProvider } from "../context/ApiKeyProvider";
import { useAlertStream, type AlertEvent } from "./useAlertStream";

const { fetchEventSourceMock } = vi.hoisted(() => ({ fetchEventSourceMock: vi.fn() }));

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
  EventStreamContentType: "text/event-stream",
}));

function wrapper({ children }: { children: ReactNode }) {
  return <ApiKeyProvider>{children}</ApiKeyProvider>;
}

function streamResponse(status: number): Response {
  return new Response(null, { status, headers: { "content-type": "text/event-stream" } });
}

function plainResponse(status: number): Response {
  return new Response(null, { status, headers: { "content-type": "application/json" } });
}

function alertMessage(envelope: AlertEvent): EventSourceMessage {
  return { id: "", event: "alert", data: JSON.stringify(envelope) };
}

const ENV_A: AlertEvent = {
  event_id: "a",
  time: "2026-05-21T10:00:00Z",
  magnitude: 5,
  latitude: 1,
  longitude: 2,
};
const ENV_B: AlertEvent = {
  event_id: "b",
  time: "2026-05-21T11:00:00Z",
  magnitude: 6,
  latitude: 3,
  longitude: 4,
};

function setup() {
  fetchEventSourceMock.mockResolvedValue(undefined);
  const view = renderHook(() => useAlertStream(), { wrapper });
  const call = fetchEventSourceMock.mock.lastCall;
  if (!call) {
    throw new Error("fetchEventSource was not called");
  }
  const options = call[1] as FetchEventSourceInit;
  return { result: view.result, options };
}

beforeEach(() => {
  window.localStorage.clear();
  setApiKey("qkf_test");
  fetchEventSourceMock.mockReset();
});

describe("useAlertStream", () => {
  it("sends the Bearer header from the configured key", () => {
    setup();
    const call = fetchEventSourceMock.mock.lastCall;
    const options = call?.[1] as FetchEventSourceInit;
    const headers = options.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer qkf_test");
  });

  it("marks the stream open on a successful connection", async () => {
    const { result, options } = setup();
    await act(async () => {
      await options.onopen?.(streamResponse(200));
    });
    expect(result.current.status).toBe("open");
  });

  it("maps alert frames to events, newest first and deduped by id", async () => {
    const { result, options } = setup();
    await act(async () => {
      await options.onopen?.(streamResponse(200));
    });

    act(() => options.onmessage?.(alertMessage(ENV_A)));
    act(() => options.onmessage?.(alertMessage(ENV_B)));
    expect(result.current.events.map((event) => event.event_id)).toEqual(["b", "a"]);

    // Re-sending A moves it to the front without growing the list.
    act(() => options.onmessage?.(alertMessage({ ...ENV_A, magnitude: 9 })));
    expect(result.current.events.map((event) => event.event_id)).toEqual(["a", "b"]);
  });

  it("treats a 400 as no-filters and stops retrying", () => {
    const { result, options } = setup();
    act(() => {
      expect(() => options.onopen?.(plainResponse(400))).toThrow();
    });
    expect(result.current.status).toBe("no-filters");
  });

  it("reports a 401 as an error with a clear message", () => {
    const { result, options } = setup();
    act(() => {
      expect(() => options.onopen?.(plainResponse(401))).toThrow();
    });
    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("API key missing or invalid");
  });

  it("falls back to connecting on a transient drop", async () => {
    const { result, options } = setup();
    await act(async () => {
      await options.onopen?.(streamResponse(200));
    });
    act(() => options.onerror?.(new Error("dropped")));
    expect(result.current.status).toBe("connecting");
  });
});
