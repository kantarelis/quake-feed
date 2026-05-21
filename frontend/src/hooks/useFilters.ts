import { useCallback, useEffect, useState } from "react";

import { apiRequest, type Schemas } from "../api/client";

export type AlertFilterRow = Schemas["AlertFilterResponse"];
export type AlertFilterInput = Schemas["AlertFilter"];

export interface UseFiltersResult {
  /** The authenticated key's persisted filters. */
  filters: AlertFilterRow[];
  /** True while the list is being (re)loaded. */
  loading: boolean;
  /** Normalized error from the last list load, else null. */
  error: string | null;
  /** Reload the list outside of a mutation. */
  refresh: () => void;
  /** POST a new filter, then reload the list. Rejects with {@link ApiError} on 422. */
  create: (body: AlertFilterInput) => Promise<void>;
  /** DELETE a filter by id, then reload the list. */
  remove: (id: number) => Promise<void>;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Failed to load filters";
}

/**
 * CRUD over `/alerts/filters`, scoped to the authenticated key.
 *
 * The list loads on mount and after every successful mutation. `create` /
 * `remove` re-throw on failure so the caller can surface the backend's 422
 * message in the form; on success they trigger a reload.
 */
export function useFilters(): UseFiltersResult {
  const [filters, setFilters] = useState<AlertFilterRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Bumping this re-runs the load effect (mount, refresh, post-mutation).
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
        const data = await apiRequest<Schemas["AlertFiltersListResponse"]>("/alerts/filters", {
          signal: controller.signal,
        });
        if (!active) {
          return;
        }
        setFilters(data.filters);
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

    return () => {
      active = false;
      controller.abort();
    };
  }, [reloadToken]);

  const create = useCallback(
    async (body: AlertFilterInput): Promise<void> => {
      await apiRequest<AlertFilterRow>("/alerts/filters", { method: "POST", json: body });
      refresh();
    },
    [refresh],
  );

  const remove = useCallback(
    async (id: number): Promise<void> => {
      await apiRequest<void>(`/alerts/filters/${id}`, { method: "DELETE" });
      refresh();
    },
    [refresh],
  );

  return { filters, loading, error, refresh, create, remove };
}
