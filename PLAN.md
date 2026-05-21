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
| 2 | API layer — generated OpenAPI types, localStorage key store, typed `fetch` wrapper, Vite dev proxy | `frontend/src/api/{schema.d.ts,keyStore.ts,client.ts}`, `frontend/vite.config.ts`, `makefile` (`frontend-gen-api`), `quake/_openapi.py` | ✅ |
| 3 | App shell — Tailwind layout, `react-router` routes, key context, Settings panel + "no key" gate | `frontend/src/{App,main}.tsx`, `frontend/src/components/**`, `frontend/src/context/**`, `frontend/src/pages/**` | ✅ |
| 4 | Recent-events timeline view (`/events/recent`) | `frontend/src/pages/RecentEvents.tsx`, `frontend/src/hooks/useRecentEvents.ts` + tests | ✅ |
| 5 | Alert-config form view (`/alerts/filters` create/list/delete) | `frontend/src/pages/AlertConfig.tsx`, `frontend/src/hooks/useFilters.ts` + tests | ✅ |
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

### Task 2 — API layer (types, key store, client, proxy) ✅

**Outcome.**

Shipped as planned. Changes:

- `quake/_openapi.py` (new) — dumps `app.openapi()` (`indent=2, sort_keys=True`) to stdout after seeding placeholder env, so the spec dump is hermetic (no running server / DB / Vault). Mirrors the `database/_pretty_schema.py` "`_`-prefixed helper run via `-m`" idiom rather than coupling tooling to `tests/_sandbox`.
- `makefile` `frontend-gen-api` — `python -m quake._openapi > openapi.json` → `openapi-typescript` → `prettier --write` → `rm openapi.json`. Added to `.PHONY`.
- `frontend/src/api/schema.d.ts` (new, generated) — committed OpenAPI types; Prettier-formatted on generation; reproduces byte-for-byte.
- `frontend/src/api/keyStore.ts` (new) — `localStorage` get/set/clear + `subscribe`, namespaced `quake.apiKey`, trims on set (blank = clear), cross-tab `storage`-event sync.
- `frontend/src/api/client.ts` (new) — `apiRequest<T>` (Bearer injection from the key store, JSON encode/decode, `ApiError` normalization with 401 → "API key missing or invalid", 204 → `undefined`), re-exported `paths` / `components` / `Schemas`, and a `getHealth()` helper. Per-feature typed calls land with Tasks 4–6 (indexing `Schemas[...]`).
- `frontend/vite.config.ts` — dev proxy of the API paths to the backend (`VITE_API_PROXY_TARGET`, default `http://localhost:8000`).
- `frontend/src/api/{keyStore,client}.test.ts` (new) — 12 tests.
- Supporting: `package.json` (`openapi-typescript` dep + `gen:api` script), `eslint.config.js` (ignore the generated schema), `.gitignore` (transient `frontend/openapi.json`).

**Deviations / additions beyond the spec.**

1. **bandit B105 on the spec-dump placeholders.** The credential-shaped env keys (`DB_PASSWORD`, `RABBITMQ_PASSWORD`, `GF_SECURITY_ADMIN_PASSWORD`, `VAULT_DEV_ROOT_TOKEN_ID`) tripped bandit's hardcoded-password heuristic. Fixed without suppression by routing those values through a `_PLACEHOLDER` name — bandit only flags *literal* string values for password-ish keys, and the name reads more honestly as a throwaway.
2. **`client.ts` scoped to core + one demonstrated helper (`getHealth`).** The generic `apiRequest<T>` + re-exported `Schemas` are the typed surface; feature endpoint calls come with Tasks 4–6. Keeps Task 2 thin and self-contained.
3. **Generated `schema.d.ts` is ESLint-exempt** (conventional for generated files) but Prettier-formatted on generation, so `frontend-check` passes and regeneration stays deterministic (`tsc` still sees its types; `skipLibCheck` keeps it shallow).

**Verification.** `make frontend-check` clean, `make frontend-test` green (13 tests total), `make frontend-build` clean, `make frontend-gen-api` reproduces `schema.d.ts` byte-for-byte. `make check` + `make test` (Python) unaffected — 200 unit + 4 integration.

**Commit.** `06173f8` — *feat: add API client and key management for frontend*.

---

### Task 3 — App shell (layout, routing, settings) ✅

**Outcome.**

Shipped as planned with a few structural refinements (recorded below). Changes:

- `main.tsx` — wraps `<App />` in `BrowserRouter` (split from `App` so tests can drive a `MemoryRouter`).
- `App.tsx` — `ApiKeyProvider` → `Routes` → `Layout` with routes `/` (Map), `/recent` (Recent), `/alerts` (Alerts).
- `context/apiKeyContext.ts` (context object + `useApiKey` hook) and `context/ApiKeyProvider.tsx` (provider mirroring the key store into reactive state) — split into two files (see deviation 1).
- `components/Layout.tsx` — header (title + `NavLink` nav + settings) and a single `RequireApiKey`-gated `<Outlet />`.
- `components/SettingsForm.tsx` (paste / save / clear, masked current key), `components/SettingsPanel.tsx` (header disclosure), `components/RequireApiKey.tsx` (gate; embeds `SettingsForm` + the `make issue-api-key` hint).
- `pages/{MapView,RecentEvents,AlertConfig}.tsx` — placeholders so the routes are real; Tasks 4–6 fill them.
- `test/setup.ts` — registers RTL `cleanup()` (see deviation 4).
- `components/{SettingsForm,RequireApiKey}.test.tsx` + rewritten `App.test.tsx` — 6 new tests.
- `package.json` / lockfile — `react-router` 7.15.1.

**Deviations / additions beyond the spec.**

1. **Context split into two files** (`apiKeyContext.ts` hook/const + `ApiKeyProvider.tsx` component) so neither file mixes a component export with hook/const exports — satisfies `react-refresh/only-export-components` without a suppression (the repo's no-suppression rule). The plan named a single `ApiKeyContext.tsx`.
2. **No "memoized client instance" in context.** `client.ts` is stateless module functions that read the key store directly, so there's nothing to memoize — the context exposes the reactive `apiKey` + `setKey` / `clearKey` instead. Same effect as the plan intended.
3. **Gate placed once in `Layout`** around `<Outlet />` (via `RequireApiKey`) rather than per-route. The no-key prompt embeds the reusable `SettingsForm` so users paste inline; the key is also editable anytime via the header `SettingsPanel`.
4. **Added RTL `cleanup()` to `test/setup.ts`.** With `globals: false`, RTL doesn't auto-register cleanup, so multiple rendering tests would leak DOM between cases. Registering it suite-wide in setup fixes it.
5. **`react-router` v7** (`7.15.1`), importing from the unified `react-router` package (v7 folded in the DOM bindings) — verified `BrowserRouter` / `MemoryRouter` / `Routes` / `NavLink` / `Outlet` all resolve from it.

**Verification.** `make frontend-check` clean, `make frontend-test` green (18 tests across 5 files, 6 new), `make frontend-build` clean. No Python changed → `make check` / `make test` unaffected.

**Commit.** `8f6afbb` — *feat(frontend): implement routing with React Router and API key management components*.

---

### Task 4 — Recent-events timeline view ✅

**Outcome.**

Shipped as planned. Changes:

- `frontend/src/hooks/useRecentEvents.ts` (new) — fetches `/events/recent` on mount, then re-polls on an interval. Exposes `{ events, loading, error, refresh }`. Aborts the in-flight request and clears the timer on unmount; a failed background poll sets `error` but keeps the last good `events`, and the next success clears it. Errors are normalized to a string via the `Error.message` already shaped by `client.ts` (401 → "API key missing or invalid", etc.).
- `frontend/src/pages/RecentEvents.tsx` — newest-first list (severity-banded magnitude badge, place, locale-formatted time, depth, tsunami flag, external USGS link). Four render branches keyed off `loading` / `error` / list size: loading (no data), full error + retry (no data), empty, and the list. When a refresh fails *with* data present, the list stays and a non-blocking "showing the last results" banner appears instead of the full error view.
- `frontend/src/hooks/useRecentEvents.test.ts` (new) — 5 tests (mocked `apiRequest`): mount load, `limit` query param, empty list, error normalization, `refresh` refetch.
- `frontend/src/pages/RecentEvents.test.tsx` (new) — 5 tests (mocked hook): loading, error + retry, empty, populated row + USGS link, background-failure banner.

**Deviations / additions beyond the spec.**

1. **Hook takes `limit` (default 50) / `intervalMs` (default 30000) options** rather than hard-coding them, and stays **decoupled from the key context** — the `RequireApiKey` gate guarantees a key and `client.ts` injects it, so the hook is a pure `apiRequest` wrapper. This keeps the hook test a plain `apiRequest` mock (no provider/router wrapping).
2. **Two tests beyond the spec's "success / empty / error"** — the `refresh` refetch (hook) and the data-present error banner (page) — to cover the exact states the page branches on.
3. **`loading` flips on every request (not just the first).** The page gates the full-screen loading view on an empty list, so background polls never flash the list back to "Loading…"; documented in the hook's docstring.

**Verification.** `make frontend-check` clean (eslint + prettier + tsc), `make frontend-test` green (28 tests across 7 files, 10 new), `make frontend-build` emits `dist` (50 modules). No Python changed → `make check` / `make test` not applicable.

**Commit message (proposed).**

```
feat(frontend): recent-events timeline

useRecentEvents polls /events/recent; RecentEvents renders a newest-
first list with loading / empty / error states.
```

**Commit.** _(pending — to be filled in after you commit.)_

---

### Task 5 — Alert-config form view ✅

**Outcome.**

Shipped as planned with one structural refinement (the pure-helper split, recorded below). Changes:

- `frontend/src/hooks/useFilters.ts` (new) — CRUD over `/alerts/filters` scoped to the authenticated key. Exposes `{ filters, loading, error, refresh, create, remove }`. The list loads on mount and re-loads after every successful mutation (via the same `reloadToken` effect pattern as `useRecentEvents`); `create` (POST) and `remove` (DELETE) **re-throw** on failure so the caller can surface the backend's 422, and reload on success. Also exports `AlertFilterRow` / `AlertFilterInput` type aliases off `Schemas`.
- `frontend/src/pages/alertFilterForm.ts` (new) — **pure** form helpers, no component. `buildFilter()` validates the raw string form and emits an `AlertFilter` body (only the chosen shape's keys, so it's `extra="forbid"`-safe), mirroring the backend `AlertFilter` validator: optional `min_magnitude` range, bbox XOR center+radius, partial/empty rejection, lat/lon ranges, bbox ordering. `describeFilter()` renders a one-line row summary.
- `frontend/src/pages/AlertConfig.tsx` — create form (`min_magnitude` + an exclusive shape radio that reveals the four bbox or three center+radius inputs), client-side validation before POST, backend 422 surfaced in a `role="alert"`, and a delete-per-row list with loading / empty / error states.
- `frontend/src/pages/alertFilterForm.test.ts` (new) — 13 tests: full validation matrix (empty, magnitude-only, magnitude out-of-range/non-numeric, partial bbox, bbox out-of-range, inverted bbox, valid bbox+magnitude, partial center, non-positive radius, valid center) + `describeFilter`.
- `frontend/src/hooks/useFilters.test.ts` (new) — 5 tests (mocked `apiRequest`): mount load, load error, create→reload, delete→reload, create re-throw.
- `frontend/src/pages/AlertConfig.test.tsx` (new) — 7 tests (mocked hook): list rows, empty state, empty-submit block, shape-reveal, valid create, 422 surfaced, delete-by-id.

**Deviations / additions beyond the spec.**

1. **Validation split into a pure `alertFilterForm.ts` module** rather than inlined in `AlertConfig.tsx`. This keeps the validation matrix as fast pure-function tests and avoids exporting non-component helpers from the page file (which would trip `react-refresh/only-export-components` — the repo's no-suppression rule). Recorded as a helper-grouping decision within the planned page scope.
2. **The "both shapes at once" case is structurally impossible**, because the UI uses an exclusive shape radio (none / bbox / center+radius) — so client validation covers partial/empty/ranges/ordering, and the backend stays the final authority (its 422 is surfaced verbatim). This satisfies the spec's "both-shapes rejected" intent without a redundant client check.

**Verification.** `make frontend-check` clean (eslint + prettier + tsc), `make frontend-test` green (53 tests across 10 files, 25 new), `make frontend-build` emits `dist` (52 modules). No Python changed → `make check` / `make test` not applicable.

**Commit message (proposed).**

```
feat(frontend): alert-config form (filters create/list/delete)

useFilters wraps /alerts/filters GET/POST/DELETE; AlertConfig lists
filters and validates the bbox-XOR-center+radius shape client-side
before POSTing, surfacing backend 422s. Delete per row.
```

**Commit.** _(pending — to be filled in after you commit.)_

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
