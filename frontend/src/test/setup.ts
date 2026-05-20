// Extends Vitest's `expect` with @testing-library/jest-dom matchers
// (toBeInTheDocument, toHaveTextContent, ...) and registers automatic DOM
// cleanup after each test. Referenced from vite.config.ts `test.setupFiles`.
import "@testing-library/jest-dom/vitest";
