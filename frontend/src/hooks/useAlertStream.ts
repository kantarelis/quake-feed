import {
  EventStreamContentType,
  fetchEventSource,
  type EventSourceMessage,
} from "@microsoft/fetch-event-source";
import { useEffect, useState } from "react";

import { useApiKey } from "../context/apiKeyContext";

// Hand-written to mirror the backend `models.alerts.AlertEnvelope`. It is *not*
// in the generated schema.d.ts: the SSE response body isn't part of the OpenAPI
// spec (FastAPI can't introspect an EventSourceResponse), so there's nothing to
// generate. Keep this in sync with models/alerts.py if that shape changes.
export interface AlertEvent {
  event_id: string;
  time: string;
  magnitude: number;
  magnitude_type?: string | null;
  depth_km?: number | null;
  latitude: number;
  longitude: number;
  place?: string | null;
  url?: string | null;
}

export type StreamStatus = "connecting" | "open" | "no-filters" | "error";

export interface UseAlertStreamResult {
  /** Live events, newest first, deduped by `event_id`. */
  events: AlertEvent[];
  status: StreamStatus;
  /** Human-readable error when `status === "error"`, else null. */
  error: string | null;
}

/** Thrown to stop fetch-event-source's retry loop on a non-recoverable open. */
class FatalStreamError extends Error {}

const MAX_EVENTS = 200;

function mergeEvent(previous: AlertEvent[], next: AlertEvent): AlertEvent[] {
  const withoutDuplicate = previous.filter((event) => event.event_id !== next.event_id);
  return [next, ...withoutDuplicate].slice(0, MAX_EVENTS);
}

/**
 * Subscribe to `/alerts/stream` over a fetch-based SSE client so the Bearer
 * header rides along (native `EventSource` can't set headers). Snapshots the
 * key's filters at connect time; a 400 means no filters are configured, surfaced
 * as `status: "no-filters"` (a prompt, not an error). Transient drops let the
 * library reconnect; the connection aborts on unmount or key change.
 */
export function useAlertStream(): UseAlertStreamResult {
  const { apiKey } = useApiKey();
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!apiKey) {
      return;
    }

    const controller = new AbortController();
    setStatus("connecting");
    setError(null);

    void fetchEventSource("/alerts/stream", {
      headers: { Authorization: `Bearer ${apiKey}`, Accept: EventStreamContentType },
      signal: controller.signal,
      openWhenHidden: true,
      onopen: (response: Response): Promise<void> => {
        const contentType = response.headers.get("content-type") ?? "";
        if (response.ok && contentType.includes(EventStreamContentType)) {
          setStatus("open");
          return Promise.resolve();
        }
        if (response.status === 400) {
          setStatus("no-filters");
          throw new FatalStreamError("no filters configured");
        }
        setStatus("error");
        setError(
          response.status === 401
            ? "API key missing or invalid"
            : `Stream failed (${response.status})`,
        );
        throw new FatalStreamError(`stream failed (${response.status})`);
      },
      onmessage: (message: EventSourceMessage): void => {
        if (message.event !== "alert" || !message.data) {
          return;
        }
        try {
          const envelope = JSON.parse(message.data) as AlertEvent;
          setEvents((previous) => mergeEvent(previous, envelope));
        } catch {
          // Ignore a malformed frame rather than tearing down the stream.
        }
      },
      onerror: (err: unknown): void => {
        if (err instanceof FatalStreamError) {
          throw err; // stop the library's automatic retry
        }
        // Transient drop — fetch-event-source will retry; reflect the state.
        setStatus("connecting");
      },
    }).catch(() => {
      // Fatal open errors and aborts settle here; state already reflects them.
    });

    return () => {
      controller.abort();
    };
  }, [apiKey]);

  return { events, status, error };
}
