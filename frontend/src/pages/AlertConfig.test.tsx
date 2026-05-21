import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { AlertFilterRow, UseFiltersResult } from "../hooks/useFilters";
import { AlertConfig } from "./AlertConfig";

const { useFiltersMock } = vi.hoisted(() => ({ useFiltersMock: vi.fn() }));

vi.mock("../hooks/useFilters", () => ({
  useFilters: useFiltersMock,
}));

const FILTER: AlertFilterRow = {
  id: 7,
  api_key_id: 1,
  min_magnitude: 5,
  created_at: "2026-05-21T00:00:00Z",
  updated_at: "2026-05-21T00:00:00Z",
};

function mockHook(value: Partial<UseFiltersResult> = {}): UseFiltersResult {
  const result: UseFiltersResult = {
    filters: [],
    loading: false,
    error: null,
    refresh: vi.fn(),
    create: vi.fn().mockResolvedValue(undefined),
    remove: vi.fn().mockResolvedValue(undefined),
    ...value,
  };
  useFiltersMock.mockReturnValue(result);
  return result;
}

beforeEach(() => {
  useFiltersMock.mockReset();
});

describe("AlertConfig", () => {
  it("lists existing filters", () => {
    mockHook({ filters: [FILTER] });
    render(<AlertConfig />);
    expect(screen.getByText(/M ≥ 5/)).toBeInTheDocument();
  });

  it("shows an empty state when there are no filters", () => {
    mockHook();
    render(<AlertConfig />);
    expect(screen.getByText(/no filters yet/i)).toBeInTheDocument();
  });

  it("blocks an empty submission with a validation message", async () => {
    const { create } = mockHook();
    render(<AlertConfig />);

    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/minimum magnitude/i);
    expect(create).not.toHaveBeenCalled();
  });

  it("reveals bounding-box inputs when that shape is selected", () => {
    mockHook();
    render(<AlertConfig />);

    fireEvent.click(screen.getByRole("radio", { name: "Bounding box" }));

    expect(screen.getByLabelText("Min latitude")).toBeInTheDocument();
  });

  it("creates a valid magnitude-only filter", async () => {
    const { create } = mockHook();
    render(<AlertConfig />);

    fireEvent.change(screen.getByLabelText(/minimum magnitude/i), { target: { value: "4.5" } });
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));

    await waitFor(() => expect(create).toHaveBeenCalledWith({ min_magnitude: 4.5 }));
  });

  it("surfaces a backend 422 from create", async () => {
    const create = vi.fn().mockRejectedValue(new ApiError(422, "empty filter"));
    mockHook({ create });
    render(<AlertConfig />);

    fireEvent.change(screen.getByLabelText(/minimum magnitude/i), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("empty filter");
  });

  it("deletes a filter by id", async () => {
    const { remove } = mockHook({ filters: [FILTER] });
    render(<AlertConfig />);

    fireEvent.click(screen.getByRole("button", { name: /delete/i }));

    await waitFor(() => expect(remove).toHaveBeenCalledWith(7));
  });
});
