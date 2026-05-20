# PLAN.md — Epic 7: Frontend (React + Vite + TypeScript + Leaflet)

**Status:** 🟡 In progress
**Epic source:** [`MASTER_PLAN.md`](MASTER_PLAN.md) — Epic 7
**Branch:** new feature branch off `kantarelis` (PRs target `kantarelis`)

---

## Goal

Ship the dashboard SPA that consumes the backend built in Epics 4–6:

- **Live map** (Leaflet) — recent events as markers, updated in realtime by subscribing to `/alerts/stream`.
- **Recent-events timeline** — newest-first list backed by `/events/recent`.
- **Alert-config form** — create / list / delete the per-key filters at `/alerts/filters` (min magnitude + bbox **XOR** center+radius), mirroring the backend's `AlertFilter` shape.
- **Settings panel** — paste an API key (issued out-of-band via `make issue-api-key`); persisted in `localStorage` and attached to every request.
- **Production serving** — the built SPA is copied into the backend image and served at `/` by FastAPI. Dev uses the Vite dev server proxied to the API.
- **A real quality gate** — ESLint + Prettier + `tsc --noEmit` + Vitest/RTL, wired into `make` targets and a CI job, mirroring the Python gate's rigor.

## Design choices (locked up-front so tasks don't re-litigate)

1. **Styling: Tailwind CSS.** Utility-first; fast to build a clean dashboard. PostCSS/Tailwind build step lives in the Vite config.
2. **Typed API client: `openapi-typescript` + a thin hand-written `fetch` wrapper.** Types are generated from the FastAPI OpenAPI spec into `frontend/src/api/schema.d.ts` (committed). Regeneration is **hermetic** — a make target dumps `app.openapi()` to JSON using sandbox-style placeholder env (no running server, CI-safe) and feeds it to `openapi-typescript`. The committed `schema.d.ts` is the source of truth the type-check runs against; the runtime client is a small typed `fetch` wrapper, no generated runtime code.
3. **Auth: API key in `localStorage`, sent as a header.** No user accounts exist (API-key-only), so a one-time "paste your key" step is unavoidable for *any* approach. The key is pasted into a Settings panel, stored in `localStorage`, and injected as `Authorization: Bearer <key>` by the fetch wrapper. The XSS exposure of a key in `localStorage` is an accepted tradeoff for a local-only single-user demo, documented in `docs/frontend.md`.
4. **SSE: `@microsoft/fetch-event-source`, not native `EventSource`.** The browser's native `EventSource` cannot set request headers, but `/alerts/stream` is Bearer-gated. `fetch-event-source` is a fetch-based SSE client that *can* send the `Authorization` header, so SSE auth stays header-based (no key in the URL, no backend change). It also gives us clean reconnect/abort control.
5. **Routing: `react-router` (`BrowserRouter`) + a FastAPI catch-all in prod.** Three client routes (map / recent / alerts). In production FastAPI serves `index.html` for any non-API, unmatched GET path so deep links resolve. API routers are registered first, so the catch-all never shadows `/events`, `/alerts`, `/admin`, `/health`, `/metrics`, `/env`, `/docs`, `/openapi.json`. (Fallback if the catch-all proves fiddly: `HashRouter`, which needs no server route — noted, not the default.)
6. **Data fetching: lightweight custom hooks over the typed client.** No TanStack Query / Redux. Recent-events is polled on an interval; the live map consumes the SSE stream. A small React context holds the API key + a "client" instance.
7. **Dev vs prod wiring.** Dev: `make frontend-dev` runs Vite with a proxy to the backend (same-origin from the app's POV → no CORS). Prod: `make frontend-build` emits `frontend/dist`, copied into the backend image by a **multi-stage Dockerfile** (Node build stage → Python runtime stage) and mounted by FastAPI.
8. **Map tiles: OpenStreetMap raster tiles.** No tile API key, consistent with the no-cloud / no-secrets-for-third-parties posture.
9. **Quality gate parity.** ESLint (typescript-eslint, strict) + Prettier + `tsc --noEmit` + Vitest/React-Testing-Library. New `make frontend-check` / `make frontend-test` targets and a `frontend` CI job parallel to `check` / `test`. The repo's "never suppress diagnostics" rule extends in spirit: no `eslint-disable`, no `@ts-ignore`/`@ts-expect-error`, no `tsconfig` loosening to dodge an error — fix the code or adjust project-wide config.
10. **Node 20 + npm.** Matches the CI Node already present for pyright. Single package manager (npm), `frontend/package-lock.json` committed.

## Out of scope

- **User accounts / login.** API-key only (decision 3). No OAuth, no sessions.
- **SSR / Next.js.** Vite SPA only.
- **State-management libraries** (Redux, Zustand) and **TanStack Query** (decision 6).
- **E2E tests** (Playwright/Cypress). Unit + component tests only this epic.
- **Editing filters in place (PATCH).** The form does create / list / delete; "edit" = delete + recreate. The backend `PATCH /alerts/filters/{id}` stays unused by the UI for now.
- **Map clustering / heatmaps / draw-a-bbox-on-the-map.** Plain markers; the alert-config form takes numeric bbox/center inputs.
- **i18n, dark-mode toggle, PWA/offline.**
- **Backend API changes.** Decisions 3–4 deliberately avoid touching auth. The only backend change in this epic is static-file serving (Task 7).

---

## Tasks

Each task is **one commit**. Frontend tasks run `make frontend-check` + `make frontend-test`; tasks touching Python also run `make check` + `make test`. Stop after each task; wait for the user before starting the next.

| # | Task | Files (new unless noted) | Status |
|---|------|--------------------------|--------|
| 1 | Scaffold Vite+React+TS, Tailwind, ESLint/Prettier/tsc/Vitest gate, make targets, CI job | `frontend/**` (scaffold), `makefile` (replace stub targets), `.github/workflows/code_quality_assurance.yml` | ✅ |
| 2 | API layer — generated OpenAPI types, localStorage key store, typed `fetch` wrapper, Vite dev proxy | `frontend/src/api/{schema.d.ts,keyStore.ts,client.ts}`, `frontend/vite.config.ts`, `makefile` (`frontend-gen-api`) | ⬜ |
| 3 | App shell — Tailwind layout, `react-router` routes, key context, Settings panel + "no key" gate | `frontend/src/{App,main}.tsx`, `frontend/src/components/**`, `frontend/src/context/**` | ⬜ |
| 4 | Recent-events timeline view (`/events/recent`) | `frontend/src/pages/RecentEvents.tsx`, `frontend/src/hooks/useRecentEvents.ts` + tests | ⬜ |
| 5 | Alert-config form view (`/alerts/filters` create/list/delete) | `frontend/src/pages/AlertConfig.tsx`, `frontend/src/hooks/useFilters.ts` + tests | ⬜ |
| 6 | Live map view — Leaflet + OSM + SSE via `fetch-event-source` | `frontend/src/pages/MapView.tsx`, `frontend/src/hooks/useAlertStream.ts` + tests | ⬜ |
| 7 | Production serving (FastAPI static + SPA catch-all) + multi-stage Dockerfile + `docs/frontend.md` | `quake/main.py`, `Dockerfile`, `docs/frontend.md`, `tests/unit/test_spa_serving.py` | ⬜ |

---

### Task 1 — Scaffold + tooling + quality gate ✅

**Outcome.**

Shipped as planned with a few version/tooling refinements (recorded below) and one environment-specific fix. Changes:

- `frontend/` Vite 6 + React 19 + TypeScript scaffold. Strict `tsconfig.json` — beyond the plan's `strict` / `noUncheckedIndexedAccess` / `noImplicitOverride`, also `exactOptionalPropertyTypes`, `verbatimModuleSyntax`, `isolatedModules`, `noUnusedLocals/Parameters`. Single tsconfig covering `src` + `vite.config.ts`.
- Tailwind CSS **v4** via the `@tailwindcss/vite` plugin (see deviation 1) + `@import "tailwindcss"` in `src/index.css`.
- ESLint 9 flat config (`eslint.config.js`): `typescript-eslint` recommended + `react-hooks` + `jsx-a11y` + `react-refresh`, with `eslint-config-prettier` last to disable formatting rules. Prettier (`.prettierrc.json`, `printWidth: 100`).
- Vitest + React Testing Library + jsdom; `src/test/setup.ts` wires `@testing-library/jest-dom/vitest`; one smoke test (`App` renders the title).
- `src/{main,App}.tsx`, `index.css`, `vite-env.d.ts`, `index.html`, `frontend/README.md`.
- `makefile`: added `NPM` / `FRONTEND_DIR` vars; replaced the three stub targets with real `frontend-install` (`npm ci`) / `frontend-dev` / `frontend-build`, plus `frontend-check` (eslint + prettier --check + `tsc --noEmit`) and `frontend-test` (vitest run).
- `.github/workflows/code_quality_assurance.yml`: new `frontend` job (Node 20, `npm ci`, `make frontend-check` + `make frontend-test`), parallel to `check` / `test`.

**Deviations / additions beyond the spec.**

1. **Tailwind v4 via `@tailwindcss/vite`, not a PostCSS pipeline.** The plan said "Tailwind wired through PostCSS"; v4 (the current line) ships its own Vite plugin and CSS-first config — no `postcss.config.js`, no `tailwind.config.js`, automatic content detection. Still Tailwind, simpler setup. Build confirms it (~5.3 kB emitted CSS).
2. **`package-lock.json` force-included in the repo `.gitignore`.** A global gitignore on this machine (`~/.config/git/ignore`) drops `package-lock.json` for every repo. Committing the lockfile is npm best practice and `npm ci` (the `frontend-install` target + the CI job) requires it, so `.gitignore` carries `!frontend/package-lock.json` (with a comment) to override the global rule. Verified the 6992-line lockfile landed in the commit.
3. **Versions pinned to current majors:** Vite 6, React 19, Vitest 3, TypeScript 5.7, ESLint 9, Tailwind 4. `engines.node >= 20`; CI Node pinned to 20 (matches the existing pyright Node step). Prettier `printWidth` 100 (vs Python's 120) for readable TSX.
4. **No Python-tool exclusions needed.** Confirmed `make check` still reports 2897 LOC (bandit) and pyright clean with `frontend/node_modules` present — the Python linters didn't traverse it, so no config changes were required.

**Verification.** `make frontend-check` (eslint + prettier + tsc) clean, `make frontend-test` green (1 test), `make frontend-build` emits `frontend/dist`. `make check` + `make test` (Python) unaffected — 200 unit + 4 integration.

**Commit.** `94bbeec` — *feat: initialize frontend with React, Vite, and Tailwind CSS*.

---

### Task 2 — API layer (types, key store, client, proxy)

**Scope.**

- `frontend/src/api/schema.d.ts` — types generated from the backend OpenAPI spec; committed.
- `makefile` `frontend-gen-api` — hermetic regen: dump `app.openapi()` to JSON with sandbox-style placeholder env (no running server), then `openapi-typescript` → `schema.d.ts`.
- `frontend/src/api/keyStore.ts` — `localStorage`-backed get / set / clear + a change subscription, namespaced key (`quake.apiKey`).
- `frontend/src/api/client.ts` — thin typed `fetch` wrapper: injects `Authorization: Bearer <key>` from the store, normalizes errors (401 → "key missing/invalid", 4xx/5xx → typed error), JSON in/out. Endpoint helpers typed against `schema.d.ts`.
- `frontend/vite.config.ts` — dev proxy of `/events`, `/alerts`, `/admin`, `/health`, `/metrics`, `/env`, `/openapi.json` to the backend.
- Unit tests: keyStore get/set/clear/subscribe; client header injection + error mapping (mocked `fetch`).

**Acceptance.** `make frontend-check` + `make frontend-test` clean. `make frontend-gen-api` reproduces `schema.d.ts` byte-for-byte (no diff). Python gate unaffected.

**Commit message (proposed).**

```
feat(frontend): typed API client, localStorage key store, dev proxy

openapi-typescript schema generated hermetically from app.openapi()
(make frontend-gen-api). keyStore persists the API key in localStorage;
client.ts is a thin typed fetch wrapper that attaches the Bearer header
and normalizes errors. Vite proxies API paths to the backend in dev.
```

---

### Task 3 — App shell (layout, routing, settings)

**Scope.**

- `frontend/src/main.tsx` / `App.tsx` — `BrowserRouter` with routes for `/` (map), `/recent`, `/alerts`.
- Tailwind app shell: header, nav, content area; responsive.
- `frontend/src/context/ApiKeyContext.tsx` — provides the key + a memoized client instance, subscribes to keyStore changes.
- Settings panel/modal: paste / save / clear the key; shows masked state when set.
- "No key configured" gate: views render a prompt (with the `make issue-api-key` hint) instead of firing unauthenticated requests.
- Tests: shell renders nav; settings form saves to keyStore; gate shows prompt when no key.

**Acceptance.** `make frontend-check` + `make frontend-test` clean.

**Commit message (proposed).**

```
feat(frontend): app shell, routing, and API-key settings panel

BrowserRouter shell (map / recent / alerts) with a Tailwind layout.
ApiKeyContext exposes the key + a client instance; a Settings panel
saves/clears the key in localStorage. Views gate behind a "set your
API key" prompt until one is configured.
```

---

### Task 4 — Recent-events timeline view

**Scope.**

- `frontend/src/hooks/useRecentEvents.ts` — fetches `/events/recent`, interval-polls, exposes loading / error / data.
- `frontend/src/pages/RecentEvents.tsx` — newest-first list (time, magnitude, place, depth, link to USGS), with loading / empty / error states.
- Tests: hook (mocked client: success, empty, error) and the page render across states.

**Acceptance.** `make frontend-check` + `make frontend-test` clean.

**Commit message (proposed).**

```
feat(frontend): recent-events timeline

useRecentEvents polls /events/recent; RecentEvents renders a newest-
first list with loading / empty / error states.
```

---

### Task 5 — Alert-config form view

**Scope.**

- `frontend/src/hooks/useFilters.ts` — list (`GET`), create (`POST`), delete (`DELETE`) against `/alerts/filters`.
- `frontend/src/pages/AlertConfig.tsx` — list current filters + a create form: `min_magnitude` and a shape selector (bbox **XOR** center+radius), with client-side validation mirroring the backend `AlertFilter` validator (partial/empty/both-shapes rejected, ranges, bbox ordering). Delete per row. Surfaces backend 422 messages.
- Tests: hook CRUD (mocked client); form validation matrix; create → list refresh; delete.

**Acceptance.** `make frontend-check` + `make frontend-test` clean.

**Commit message (proposed).**

```
feat(frontend): alert-config form (filters create/list/delete)

useFilters wraps /alerts/filters GET/POST/DELETE; AlertConfig lists
filters and validates the bbox-XOR-center+radius shape client-side
before POSTing, surfacing backend 422s. Delete per row.
```

---

### Task 6 — Live map view (Leaflet + SSE)

**Scope.**

- `frontend/src/hooks/useAlertStream.ts` — opens `/alerts/stream` via `@microsoft/fetch-event-source` (Bearer header), parses `event: alert` envelopes, exposes the live event list + connection state; aborts cleanly on unmount / key change. Handles 400 (no filters) with a "configure a filter" prompt.
- `frontend/src/pages/MapView.tsx` — Leaflet map (OSM tiles) seeded with `/events/recent` markers, then live markers appended/updated from the SSE hook. Popups show magnitude / place / time.
- Tests: SSE envelope→marker mapping (mock `fetchEventSource`); map component renders + handles the no-filters state.

**Acceptance.** `make frontend-check` + `make frontend-test` clean.

**Commit message (proposed).**

```
feat(frontend): live Leaflet map with SSE alerts

MapView renders OSM tiles seeded from /events/recent, then plots live
events from useAlertStream — /alerts/stream consumed via fetch-event-
source so the Bearer header rides along. No filters → prompt to add one.
```

---

### Task 7 — Production serving + Dockerfile + docs

**Scope.**

- `quake/main.py` — serve `frontend/dist` (Tailwind/Vite build) at `/` via `StaticFiles`, plus a catch-all GET returning `index.html` for unmatched non-API paths (SPA deep links). API routers registered first so nothing is shadowed. No-op gracefully when `dist` is absent (dev backend without a build).
- `Dockerfile` — multi-stage: Node 20 stage runs `npm ci && npm run build` to produce `frontend/dist`; the Python runtime stage copies `dist` in. Backend + worker + beat keep the same final image.
- `makefile` — ensure `frontend-build` output path matches what the backend serves.
- `docs/frontend.md` — architecture (dev proxy vs prod serving), the key-in-localStorage tradeoff, why fetch-event-source over native EventSource, how to issue a key + paste it, the OpenAPI-type regen workflow.
- `tests/unit/test_spa_serving.py` — `index.html` served at `/` and an unknown client route; API routes (`/health`, `/events/recent`) still resolve and aren't shadowed.

**Acceptance.** `make frontend-build` emits `dist`; backend serves it; `make check` + `make test` (Python) green; `make frontend-check` + `make frontend-test` green.

**Commit message (proposed).**

```
feat(frontend): serve the SPA from FastAPI + multi-stage Docker build

FastAPI mounts frontend/dist at / with an index.html catch-all for SPA
deep links (API routers matched first). A multi-stage Dockerfile builds
the frontend in a Node stage and copies dist into the Python image.
docs/frontend.md covers dev-proxy vs prod-serving and the auth model.
```

---

## After all tasks ship

- User confirms commit range, then asks Claude to:
  - Mark Epic 7 ✅ Done in `MASTER_PLAN.md` with the commit range.
  - Archive this `PLAN.md` to `docs/history/epic-07-frontend.md` (single rename commit).
- Root `PLAN.md` slot is then free for Epic 8 (Observability).
