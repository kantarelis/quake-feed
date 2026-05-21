import { useCallback, useEffect, useState } from "react";

import { apiRequest, type Schemas } from "../api/client";

export type RecentEvent = Schemas["EventResponse"];

export interface UseRecentEventsOptions {
  /** Maximum number of events to request. The backend caps this at 1000. */
  limit?: number;
  /** Background poll interval in milliseconds. Pass 0 to fetch only once. */
  intervalMs?: number;
}

export interface UseRecentEventsResult {
  /** Latest events, newest first (the backend already orders them). */
  events: RecentEvent[];
  /** True while a request is in flight. */
  loading: boolean;
  /** Normalized error message from the last failed request, else null. */
  error: string | null;
  /** Trigger an immediate refetch outside the poll schedule. */
  refresh: () => void;
}

const DEFAULT_LIMIT = 50;
const DEFAULT_INTERVAL_MS = 30_000;

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Failed to load recent events";
}

/**
 * Fetch `/events/recent` on mount, then re-poll on an interval.
 *
 * `loading` flips on every request; consumers that already have data should
 * keep showing it across background polls (gate the loading view on an empty
 * list). A failed background poll sets `error` but leaves the last good
 * `events` in place; the next success clears it.
 */
export function useRecentEvents(options: UseRecentEventsOptions = {}): UseRecentEventsResult {
  const { limit = DEFAULT_LIMIT, intervalMs = DEFAULT_INTERVAL_MS } = options;

  const [events, setEvents] = useState<RecentEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Bumping this re-runs the effect, forcing an out-of-schedule refetch.
  const [reloadToken, setReloadToken] = useState(0);

  const refresh = useCallback(() => {
    setReloadToken((token) => token + 1);
  }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    async function load(): Promise<void> {
      setLoading(true);
      try {
        const data = await apiRequest<Schemas["EventsListResponse"]>(
          `/events/recent?limit=${limit}`,
          { signal: controller.signal },
        );
        if (!active) {
          return;
        }
        setEvents(data.events);
        setError(null);
      } catch (err) {
        if (!active || controller.signal.aborted) {
          return;
        }
        setError(messageOf(err));
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void load();

    const timer =
      intervalMs > 0
        ? window.setInterval(() => {
            void load();
          }, intervalMs)
        : undefined;

    return () => {
      active = false;
      controller.abort();
      if (timer !== undefined) {
        window.clearInterval(timer);
      }
    };
  }, [limit, intervalMs, reloadToken]);

  return { events, loading, error, refresh };
}
