import { useRecentEvents, type RecentEvent } from "../hooks/useRecentEvents";

/** Tailwind classes for the magnitude badge, banded by severity. */
function magnitudeClass(magnitude: number): string {
  if (magnitude >= 6) {
    return "bg-red-100 text-red-800";
  }
  if (magnitude >= 4) {
    return "bg-amber-100 text-amber-800";
  }
  if (magnitude >= 2) {
    return "bg-emerald-100 text-emerald-800";
  }
  return "bg-slate-100 text-slate-700";
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function formatDepth(depthKm: number | null | undefined): string {
  return depthKm == null ? "depth n/a" : `${depthKm.toFixed(1)} km deep`;
}

function EventRow({ event }: { event: RecentEvent }) {
  const magnitude = event.magnitude.toFixed(1);
  const magnitudeType = event.magnitude_type ? ` ${event.magnitude_type}` : "";

  return (
    <li className="flex items-center gap-4 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <span
        className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-md text-base font-semibold ${magnitudeClass(
          event.magnitude,
        )}`}
        title={`Magnitude ${magnitude}${magnitudeType}`}
      >
        {magnitude}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium text-slate-900">{event.place ?? "Unknown location"}</p>
        <p className="mt-0.5 text-sm text-slate-500">
          {formatTime(event.time)} · {formatDepth(event.depth_km)}
          {event.tsunami ? " · tsunami" : ""}
        </p>
      </div>
      {event.url ? (
        <a
          href={event.url}
          target="_blank"
          rel="noreferrer"
          className="shrink-0 text-sm font-medium text-slate-500 hover:text-slate-900"
        >
          USGS ↗
        </a>
      ) : null}
    </li>
  );
}

/** Newest-first timeline of recent earthquakes, backed by `/events/recent`. */
export function RecentEvents() {
  const { events, loading, error, refresh } = useRecentEvents();
  const hasEvents = events.length > 0;

  return (
    <section>
      <header className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Recent events</h1>
          <p className="mt-1 text-sm text-slate-500">
            Newest earthquakes, refreshed automatically.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="shrink-0 rounded border border-slate-300 px-3 py-1 text-sm text-slate-700 hover:bg-slate-100"
        >
          Refresh
        </button>
      </header>

      {error && hasEvents ? (
        <p className="mt-4 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Couldn’t refresh ({error}). Showing the last results.
        </p>
      ) : null}

      <div className="mt-4">
        {loading && !hasEvents ? (
          <p className="text-sm text-slate-500">Loading recent events…</p>
        ) : error && !hasEvents ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <p>Failed to load events: {error}</p>
            <button
              type="button"
              onClick={refresh}
              className="mt-2 rounded border border-red-300 px-3 py-1 font-medium hover:bg-red-100"
            >
              Try again
            </button>
          </div>
        ) : !hasEvents ? (
          <p className="text-sm text-slate-500">No earthquakes reported yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {events.map((event) => (
              <EventRow key={event.event_id} event={event} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
