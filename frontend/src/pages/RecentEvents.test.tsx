import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RecentEvent, UseRecentEventsResult } from "../hooks/useRecentEvents";
import { RecentEvents } from "./RecentEvents";

const { useRecentEventsMock } = vi.hoisted(() => ({ useRecentEventsMock: vi.fn() }));

vi.mock("../hooks/useRecentEvents", () => ({
  useRecentEvents: useRecentEventsMock,
}));

const SAMPLE: RecentEvent = {
  event_id: "us1",
  time: "2026-05-21T10:00:00Z",
  magnitude: 5.2,
  place: "100km W of Nowhere",
  depth_km: 12.34,
  latitude: 1,
  longitude: 2,
  tsunami: false,
  url: "https://earthquake.usgs.gov/us1",
};

function mockHook(value: Partial<UseRecentEventsResult>): void {
  useRecentEventsMock.mockReturnValue({
    events: [],
    loading: false,
    error: null,
    refresh: vi.fn(),
    ...value,
  });
}

beforeEach(() => {
  useRecentEventsMock.mockReset();
});

describe("RecentEvents", () => {
  it("shows a loading message before the first load resolves", () => {
    mockHook({ loading: true });
    render(<RecentEvents />);
    expect(screen.getByText(/loading recent events/i)).toBeInTheDocument();
  });

  it("shows an error with a retry when the first load fails", () => {
    mockHook({ error: "API key missing or invalid" });
    render(<RecentEvents />);
    expect(screen.getByText(/failed to load events/i)).toBeInTheDocument();
    expect(screen.getByText(/api key missing or invalid/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("shows an empty message when there are no events", () => {
    mockHook({});
    render(<RecentEvents />);
    expect(screen.getByText(/no earthquakes reported yet/i)).toBeInTheDocument();
  });

  it("renders an event row with magnitude, place and a USGS link", () => {
    mockHook({ events: [SAMPLE] });
    render(<RecentEvents />);

    expect(screen.getByText("100km W of Nowhere")).toBeInTheDocument();
    expect(screen.getByText("5.2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /usgs/i })).toHaveAttribute(
      "href",
      "https://earthquake.usgs.gov/us1",
    );
  });

  it("keeps showing events with a banner when a background refresh fails", () => {
    mockHook({ events: [SAMPLE], error: "network down" });
    render(<RecentEvents />);

    expect(screen.getByText(/showing the last results/i)).toBeInTheDocument();
    expect(screen.getByText("100km W of Nowhere")).toBeInTheDocument();
    // The full-screen error view (with retry) is reserved for the no-data case.
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });
});
