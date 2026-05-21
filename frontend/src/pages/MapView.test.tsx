import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AlertEvent, StreamStatus } from "../hooks/useAlertStream";
import type { RecentEvent } from "../hooks/useRecentEvents";
import { MapView } from "./MapView";

const { useRecentEventsMock, useAlertStreamMock } = vi.hoisted(() => ({
  useRecentEventsMock: vi.fn(),
  useAlertStreamMock: vi.fn(),
}));

vi.mock("../hooks/useRecentEvents", () => ({ useRecentEvents: useRecentEventsMock }));
vi.mock("../hooks/useAlertStream", () => ({ useAlertStream: useAlertStreamMock }));

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children?: ReactNode }) => <div data-testid="map">{children}</div>,
  TileLayer: () => <div data-testid="tiles" />,
  CircleMarker: ({ children }: { children?: ReactNode }) => (
    <div data-testid="marker">{children}</div>
  ),
  Popup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
}));

function recentEvent(overrides: Partial<RecentEvent>): RecentEvent {
  return {
    event_id: "seed",
    time: "2026-05-21T10:00:00Z",
    magnitude: 5.2,
    latitude: 1,
    longitude: 2,
    place: "Seed place",
    tsunami: false,
    ...overrides,
  };
}

function liveEvent(overrides: Partial<AlertEvent>): AlertEvent {
  return {
    event_id: "live",
    time: "2026-05-21T11:00:00Z",
    magnitude: 7,
    latitude: 3,
    longitude: 4,
    ...overrides,
  };
}

function setup(options: {
  recent?: RecentEvent[];
  live?: AlertEvent[];
  status?: StreamStatus;
}): void {
  useRecentEventsMock.mockReturnValue({
    events: options.recent ?? [],
    loading: false,
    error: null,
    refresh: vi.fn(),
  });
  useAlertStreamMock.mockReturnValue({
    events: options.live ?? [],
    status: options.status ?? "open",
    error: null,
  });
}

function renderMap(): void {
  render(
    <MemoryRouter>
      <MapView />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useRecentEventsMock.mockReset();
  useAlertStreamMock.mockReset();
});

describe("MapView", () => {
  it("renders a marker for each seed event with a popup", () => {
    setup({ recent: [recentEvent({})] });
    renderMap();

    expect(screen.getAllByTestId("marker")).toHaveLength(1);
    expect(screen.getByText("M 5.2")).toBeInTheDocument();
    expect(screen.getByText("Seed place")).toBeInTheDocument();
  });

  it("lets a live event override the seed event with the same id", () => {
    setup({
      recent: [recentEvent({ event_id: "shared", magnitude: 3 })],
      live: [liveEvent({ event_id: "shared", magnitude: 7 })],
    });
    renderMap();

    expect(screen.getAllByTestId("marker")).toHaveLength(1);
    expect(screen.getByText("M 7.0")).toBeInTheDocument();
  });

  it("shows the live status indicator", () => {
    setup({ status: "open" });
    renderMap();
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("prompts to configure a filter when none are set", () => {
    setup({ status: "no-filters" });
    renderMap();

    expect(screen.getByText(/live updates need a filter/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /configure one/i })).toHaveAttribute("href", "/alerts");
  });
});
