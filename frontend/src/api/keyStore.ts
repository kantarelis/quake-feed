// Persistence for the API key the SPA sends on every request.
//
// There are no user accounts (API-key auth only), so the key is pasted into
// the Settings panel (Task 3) and kept in localStorage. The client wrapper
// (./client.ts) reads it on each request; components subscribe so they can
// react to "key set" / "key cleared" without a full reload.
//
// Tradeoff: a key in localStorage is readable by any script that achieves XSS.
// Accepted for a local-only, single-user demo (documented in docs/frontend.md).

const STORAGE_KEY = "quake.apiKey";

type Listener = (key: string | null) => void;

const listeners = new Set<Listener>();

export function getApiKey(): string | null {
  return window.localStorage.getItem(STORAGE_KEY);
}

export function setApiKey(key: string): void {
  const trimmed = key.trim();
  if (!trimmed) {
    // A blank value is a clear, not a stored empty key.
    clearApiKey();
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, trimmed);
  notify();
}

export function clearApiKey(): void {
  window.localStorage.removeItem(STORAGE_KEY);
  notify();
}

export function subscribeApiKey(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function notify(): void {
  const key = getApiKey();
  for (const listener of listeners) {
    listener(key);
  }
}

// Cross-tab sync: the `storage` event fires in *other* tabs when localStorage
// changes, so a key set/cleared in one tab propagates to the rest.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) {
      notify();
    }
  });
}
