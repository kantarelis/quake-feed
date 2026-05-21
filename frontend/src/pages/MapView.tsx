import "leaflet/dist/leaflet.css";

import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";
import { Link } from "react-router";

import { useAlertStream, type AlertEvent, type StreamStatus } from "../hooks/useAlertStream";
import { useRecentEvents, type RecentEvent } from "../hooks/useRecentEvents";

interface MarkerEvent {
  event_id: string;
  latitude: number;
  longitude: number;
  magnitude: number;
  place: string | null | undefined;
  time: string;
  url: string | null | undefined;
}

const STATUS_LABEL: Record<StreamStatus, string> = {
  connecting: "Connecting…",
  open: "Live",
  "no-filters": "No filters",
  error: "Disconnected",
};

const STATUS_DOT: Record<StreamStatus, string> = {
  connecting: "bg-amber-400",
  open: "bg-emerald-500",
  "no-filters": "bg-slate-400",
  error: "bg-red-500",
};

function toMarker(event: RecentEvent | AlertEvent): MarkerEvent {
  return {
    event_id: event.event_id,
    latitude: event.latitude,
    longitude: event.longitude,
    magnitude: event.magnitude,
    place: event.place,
    time: event.time,
    url: event.url,
  };
}

/** Live events override the recent-events seed where ids collide. */
function mergeMarkers(recent: RecentEvent[], live: AlertEvent[]): MarkerEvent[] {
  const byId = new Map<string, MarkerEvent>();
  for (const event of recent) {
    byId.set(event.event_id, toMarker(event));
  }
  for (const event of live) {
    byId.set(event.event_id, toMarker(event));
  }
  return [...byId.values()];
}

function markerColor(magnitude: number): string {
  if (magnitude >= 6) {
    return "#dc2626";
  }
  if (magnitude >= 4) {
    return "#d97706";
  }
  if (magnitude >= 2) {
    return "#059669";
  }
  return "#64748b";
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Live Leaflet map: OSM tiles seeded from /events/recent, then live SSE alerts. */
export function MapView() {
  const { events: recent } = useRecentEvents();
  const { events: live, status } = useAlertStream();
  const markers = mergeMarkers(recent, live);

  return (
    <section className="flex flex-col gap-4">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Live map</h1>
          <p className="mt-1 text-sm text-slate-500">
            Recent earthquakes, with live updates from your alert filters.
          </p>
        </div>
        <span className="flex shrink-0 items-center gap-2 text-sm text-slate-600">
          <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[status]}`} aria-hidden="true" />
          {STATUS_LABEL[status]}
        </span>
      </header>

      {status === "no-filters" ? (
        <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          No alert filters configured — the map shows recent events, but live updates need a filter.{" "}
          <Link to="/alerts" className="font-medium underline">
            Configure one
          </Link>
          .
        </p>
      ) : null}

      <MapContainer
        center={[20, 0]}
        zoom={2}
        scrollWheelZoom
        className="h-[70vh] w-full rounded-lg border border-slate-200"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {markers.map((marker) => (
          <CircleMarker
            key={marker.event_id}
            center={[marker.latitude, marker.longitude]}
            radius={4 + marker.magnitude * 1.5}
            pathOptions={{ color: markerColor(marker.magnitude), weight: 1, fillOpacity: 0.6 }}
          >
            <Popup>
              <p className="font-semibold">M {marker.magnitude.toFixed(1)}</p>
              <p>{marker.place ?? "Unknown location"}</p>
              <p className="text-slate-500">{formatTime(marker.time)}</p>
              {marker.url ? (
                <a
                  href={marker.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-slate-600 underline"
                >
                  USGS details ↗
                </a>
              ) : null}
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </section>
  );
}
