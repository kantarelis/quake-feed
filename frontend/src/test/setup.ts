// Extends Vitest's `expect` with @testing-library/jest-dom matchers
// (toBeInTheDocument, ...) and unmounts rendered trees after each test.
// RTL's auto-cleanup only fires when the test globals are injected; we run
// with `globals: false`, so register cleanup explicitly here.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
