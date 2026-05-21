import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { getApiKey } from "../api/keyStore";
import { ApiKeyProvider } from "../context/ApiKeyProvider";
import { SettingsForm } from "./SettingsForm";

beforeEach(() => {
  window.localStorage.clear();
});

function renderForm() {
  render(
    <ApiKeyProvider>
      <SettingsForm />
    </ApiKeyProvider>,
  );
}

describe("SettingsForm", () => {
  it("saves a pasted key to the store and shows it masked", () => {
    renderForm();
    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "qkf_0123456789abcdef" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(getApiKey()).toBe("qkf_0123456789abcdef");
    expect(screen.getByText(/current key:/i)).toBeInTheDocument();
  });

  it("clears the stored key", () => {
    renderForm();
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "qkf_abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(getApiKey()).toBeNull();
    expect(screen.getByText(/no key set/i)).toBeInTheDocument();
  });
});
