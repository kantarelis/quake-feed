# Frontend — dashboard SPA (React + Vite + Leaflet)

The dashboard is a single-page app under `frontend/` that consumes the public
read API: a live Leaflet map, a recent-events timeline, and an alert-filter
form. It is a thin client — all domain logic stays in the backend; the SPA only
renders state and issues authenticated requests.

This document covers how the app is wired in development vs production, the
auth model and its tradeoffs, why SSE uses `fetch-event-source` instead of the
native `EventSource`, and the typed-API regeneration workflow.

## Stack

| Concern        | Choice                                                      |
| -------------- | ----------------------------------------------------------- |
| Build / dev    | Vite 6                                                      |
| UI             | React 19 + TypeScript (strict)                              |
| Styling        | Tailwind CSS v4 (`@tailwindcss/vite`)                       |
| Routing        | `react-router` v7 (`BrowserRouter`)                         |
| Map            | `react-leaflet` v5 + Leaflet, OpenStreetMap raster tiles    |
| SSE            | `@microsoft/fetch-event-source`                             |
| API types      | `openapi-typescript` (generated from the FastAPI spec)      |
| Quality gate   | ESLint (typescript-eslint strict) + Prettier + `tsc` + Vitest/RTL |

## Dev vs production wiring

The app always talks to **same-origin, relative** API paths (`/events/recent`,
`/alerts/stream`, …). What sits behind that origin differs by environment:

```
 Development                              Production
 ───────────                              ──────────
 browser → Vite dev server (5173)         browser → FastAPI (8000)
            │  proxy /events,/alerts,…                │  StaticFiles + catch-all
            ▼                                         ▼
          FastAPI (8000)                            frontend/dist (built SPA)
```

- **Development** — `make frontend-dev` runs the Vite dev server. `vite.config.ts`
  proxies the API path prefixes (`/events`, `/alerts`, `/admin`, `/health`,
  `/metrics`, `/env`, `/openapi.json`) to the backend (default
  `http://localhost:8000`, override with `VITE_API_PROXY_TARGET`). Because the
  browser only ever sees the dev-server origin, there is **no CORS** and the
  backend needs no CORS config.

- **Production** — `make frontend-build` emits `frontend/dist`. FastAPI serves it:
  `Quake._mount_spa` (`quake/main.py`) registers a catch-all **after** all API
  routers, so every API path — and FastAPI's own `/docs` / `/openapi.json` —
  matches first and is never shadowed. Any other GET returns the requested file
  from `dist` if it exists, else `index.html`, so client-side deep links
  (`/recent`, `/alerts`) resolve. Path traversal is rejected (`is_relative_to`).
  When `frontend/dist` is absent (a dev backend with no build) the catch-all is
  simply not mounted — the API runs unchanged.

The **multi-stage `Dockerfile`** mirrors this: a `node:20-slim` stage runs
`npm ci && npm run build`, and the Python runtime stage copies `/frontend/dist`
into the image at `frontend/dist`. Node never ships in the final image; the
backend, Celery worker, and beat keep sharing the one image.

## Auth — API key in `localStorage`

There are **no user accounts** (see `docs/vault.md` / the API-key auth model).
Clients authenticate with `Authorization: Bearer <api-key>`. The flow:

1. Issue a key out-of-band: `make issue-api-key` writes a new key to Vault and
   prints it **once**.
2. Paste it into the dashboard's Settings panel (header) or the "API key
   required" gate shown when no key is set.
3. The key is stored in `localStorage` (`quake.apiKey`) and injected as the
   Bearer header by the `fetch` wrapper (`src/api/client.ts`) on every request.

**Tradeoff.** A key in `localStorage` is readable by any script running on the
page, so it is exposed to XSS. This is an accepted tradeoff for a **local-only,
single-user demo**: there are no accounts to protect, the key is revocable
(`quake.api_keys`), and the deployment is not internet-facing. A hosted,
multi-user version would move to short-lived tokens in memory + an
HTTP-only refresh cookie — out of scope here.

## SSE — why `fetch-event-source`, not native `EventSource`

`/alerts/stream` is Bearer-gated. The browser's native `EventSource` **cannot
set request headers**, so it can't send `Authorization` — the only escape hatch
would be putting the key in the URL (logged, cached, leak-prone) or weakening
the endpoint's auth.

`@microsoft/fetch-event-source` is a `fetch`-based SSE client that **can** send
arbitrary headers, so the Bearer header rides along and the endpoint stays
header-authenticated with no backend change. It also gives clean
abort/reconnect control. `useAlertStream` (`src/hooks/useAlertStream.ts`) uses
this to:

- send the Bearer header and abort on unmount / key change,
- treat a `400` (no filters configured) as a "configure a filter" prompt rather
  than an error,
- stop retrying on fatal opens (`400`/`401`) but let transient drops reconnect.

The SSE payload type (`AlertEvent`) is **hand-written** to mirror the backend
`models.alerts.AlertEnvelope`: an `EventSourceResponse` body is not part of the
OpenAPI spec, so it cannot be generated (see below). Keep it in sync with
`models/alerts.py`.

## Typed API client — generation workflow

Request/response types come from the backend's own OpenAPI spec, so the
frontend and backend can't drift silently. The committed
`src/api/schema.d.ts` is the source of truth the type-check runs against; the
runtime client (`src/api/client.ts`) is a small hand-written `fetch` wrapper —
no generated runtime code.

Regenerate after any change to an API request/response model:

```bash
make frontend-gen-api
```

This runs `python -m quake._openapi` (which dumps `app.openapi()` to JSON under
**placeholder env** — no running server, DB, or Vault, so it's CI-safe),
feeds it to `openapi-typescript`, formats the output with Prettier, and removes
the transient `openapi.json`. The result is deterministic — regenerating with
no API change reproduces `schema.d.ts` byte-for-byte. Commit the regenerated
file alongside the backend change.

> SSE bodies are intentionally absent from the spec (FastAPI can't introspect
> `EventSourceResponse`), which is why `AlertEvent` is hand-written rather than
> generated.

## Quality gate

The frontend has its own gate, parallel to the Python one and held to the same
"never suppress diagnostics" rule (no `eslint-disable`, no `@ts-ignore` /
`@ts-expect-error`, no `tsconfig` loosening — fix the code or adjust
project-wide config):

```bash
make frontend-check   # eslint + prettier --check + tsc --noEmit
make frontend-test    # vitest run (unit + component tests)
```

Both run in the `frontend` CI job. Component tests use React Testing Library +
jsdom; Leaflet is mocked in tests (it needs real DOM geometry), and the real
bundle is exercised by `make frontend-build`.
