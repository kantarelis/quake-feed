import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { setApiKey } from "../api/keyStore";
import { ApiKeyProvider } from "../context/ApiKeyProvider";
import { RequireApiKey } from "./RequireApiKey";

beforeEach(() => {
  window.localStorage.clear();
});

function renderGate() {
  render(
    <ApiKeyProvider>
      <RequireApiKey>
        <div>secret data</div>
      </RequireApiKey>
    </ApiKeyProvider>,
  );
}

describe("RequireApiKey", () => {
  it("shows the prompt and hides children when no key is configured", () => {
    renderGate();
    expect(screen.getByText(/api key required/i)).toBeInTheDocument();
    expect(screen.queryByText("secret data")).not.toBeInTheDocument();
  });

  it("renders children when a key is configured", () => {
    setApiKey("qkf_abc");
    renderGate();
    expect(screen.getByText("secret data")).toBeInTheDocument();
    expect(screen.queryByText(/api key required/i)).not.toBeInTheDocument();
  });
});
