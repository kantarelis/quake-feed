import { beforeEach, describe, expect, it } from "vitest";

import { clearApiKey, getApiKey, setApiKey, subscribeApiKey } from "./keyStore";

beforeEach(() => {
  window.localStorage.clear();
});

describe("keyStore", () => {
  it("returns null when no key is stored", () => {
    expect(getApiKey()).toBeNull();
  });

  it("stores and reads a key", () => {
    setApiKey("qkf_abc");
    expect(getApiKey()).toBe("qkf_abc");
  });

  it("trims surrounding whitespace and treats a blank value as a clear", () => {
    setApiKey("  qkf_x  ");
    expect(getApiKey()).toBe("qkf_x");

    setApiKey("   ");
    expect(getApiKey()).toBeNull();
  });

  it("clears a stored key", () => {
    setApiKey("qkf_abc");
    clearApiKey();
    expect(getApiKey()).toBeNull();
  });

  it("notifies subscribers on set and clear, and stops after unsubscribe", () => {
    const seen: (string | null)[] = [];
    const unsubscribe = subscribeApiKey((key) => seen.push(key));

    setApiKey("qkf_1");
    clearApiKey();
    unsubscribe();
    setApiKey("qkf_2"); // after unsubscribe — must not be recorded

    expect(seen).toEqual(["qkf_1", null]);
  });
});
