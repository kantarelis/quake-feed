import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";

import App from "./App";

beforeEach(() => {
  window.localStorage.clear();
});

function renderApp() {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
}

describe("App shell", () => {
  it("renders the title and primary navigation", () => {
    renderApp();
    expect(screen.getByText("quake-feed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Map" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Recent" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Alerts" })).toBeInTheDocument();
  });

  it("gates content behind the API-key prompt when no key is set", () => {
    renderApp();
    expect(screen.getByText(/api key required/i)).toBeInTheDocument();
    expect(screen.getByText(/make issue-api-key/i)).toBeInTheDocument();
    // The placeholder page content is not rendered while gated.
    expect(screen.queryByText(/coming in task 6/i)).not.toBeInTheDocument();
  });
});
