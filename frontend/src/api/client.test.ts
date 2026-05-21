import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest } from "./client";
import { clearApiKey, setApiKey } from "./keyStore";

const fetchMock = vi.fn();

beforeEach(() => {
  window.localStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function lastRequestInit(): RequestInit {
  const call = fetchMock.mock.lastCall;
  if (!call) {
    throw new Error("fetch was not called");
  }
  return (call[1] as RequestInit | undefined) ?? {};
}

describe("apiRequest", () => {
  it("attaches the Bearer header when a key is configured", async () => {
    setApiKey("qkf_abc");
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await apiRequest("/events/recent");

    const headers = lastRequestInit().headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer qkf_abc");
  });

  it("omits the Bearer header when no key is configured", async () => {
    clearApiKey();
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await apiRequest("/events/recent");

    const headers = lastRequestInit().headers as Headers;
    expect(headers.has("Authorization")).toBe(false);
  });

  it("sends a JSON body and content-type for options.json", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1 }, 201));

    await apiRequest("/alerts/filters", { method: "POST", json: { min_magnitude: 4 } });

    const init = lastRequestInit();
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ min_magnitude: 4 }));
    expect((init.headers as Headers).get("Content-Type")).toBe("application/json");
  });

  it("decodes and returns the JSON body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ count: 2 }));

    const data = await apiRequest<{ count: number }>("/events/recent");

    expect(data).toEqual({ count: 2 });
  });

  it("resolves to undefined for a 204", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    await expect(apiRequest("/alerts/filters/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("maps 401 to a clear message", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "invalid api key" }, 401));

    const error = await apiRequest("/events/recent").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).message).toBe("API key missing or invalid");
  });

  it("surfaces the backend detail on other 4xx responses", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "no filters configured" }, 400));

    await expect(apiRequest("/alerts/stream")).rejects.toThrow("no filters configured");
  });
});
