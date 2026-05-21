import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev-only: the SPA is same-origin in production (the backend serves it), so in
// development we proxy the API paths to the backend to mirror that. Override the
// target with VITE_API_PROXY_TARGET. Vitest ignores `server`.
const API_PROXY_TARGET = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";
const API_PATHS = ["/events", "/alerts", "/admin", "/health", "/metrics", "/env", "/openapi.json"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: Object.fromEntries(
      API_PATHS.map((path) => [path, { target: API_PROXY_TARGET, changeOrigin: true }]),
    ),
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
