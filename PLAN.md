# PLAN.md — Epic 4: Read API (events endpoints)

**Status:** 🟡 In progress
**Epic source:** [`MASTER_PLAN.md`](MASTER_PLAN.md) — Epic 4
**Branch:** `develop` (PRs target `kantarelis`)

---

## Goal

Expose the data ingested by Epic 3 over an HTTP read API:

- `GET /events/recent?limit=N` — last N events, newest first (convenience).
- `GET /events?near=lat,lon&radius_km=R&min_magnitude=X&since=T&limit=N` — single combined-filter endpoint, every query param optional and combinable.
- `GET /metrics` — Prometheus exposition (uses the metrics already registered by `functions/celery_metrics.py`, plus future API metrics).
- `GET /env` — running environment summary (environment, application name, version).

Each endpoint is documented in the auto-generated OpenAPI spec.

## Design choices (captured up-front so tasks don't re-litigate them)

1. **URL shape.** One `/events` route with all four filters as optional query params; `/events/recent` is a dedicated convenience route that wraps `EventsETL.recent(limit)`. The combined `/events` route requires a new `EventsETL.query(...)` method — composing the existing `near` / `by_magnitude` methods would require materializing both result sets in memory and intersecting them, which the SQL layer can do trivially in one statement.
2. **Auth.** Read endpoints are **public** in this epic. Epic 5 introduces the `Authenticate` dependency and retrofits it onto every protected route. No stub auth dep is added now (avoid backwards-compat hacks per `CLAUDE.md`).
3. **`/metrics` + `/env` location.** Both live in `quake/api/main/` (the existing `MainManager`), matching the directory layout in `MASTER_PLAN.md` and `CLAUDE.md`. Epic 8 adds **more** metrics on top; this epic only exposes the endpoint and the metric registry already in place.
4. **`near` parameter shape.** Single comma-separated string `near=lat,lon` (matches `MASTER_PLAN.md`), parsed and validated in a Pydantic model. `near` and `radius_km` must be provided together — partial input returns HTTP 422.
5. **DB-row vs. response DTO.** API responses use a public `EventResponse` model that mirrors `EventRow` minus internal-only fields (`inserted_at`, `updated_at`). Domain-level `Event` model under `models/events.py` is **deferred** — not needed until SSE (Epic 6) wants a shared envelope shape.
6. **Test pattern.** Per-endpoint unit tests use `fastapi.testclient.TestClient` against a freshly-instantiated `Quake` app, seeded against the sandbox DB the existing `tests/unit/conftest.py` already provides. No new fixtures required. An end-to-end smoke test under `tests/integration/` exercises the full wire-up once.

## Out of scope

- Auth, scopes, admin endpoints (Epic 5).
- `/alerts/stream`, persistent filter CRUD (Epic 6).
- Pagination beyond `limit` (no cursors). Acceptable because the result sets are bounded by `limit` and by `since` on the magnitude path.
- New Prometheus metrics for HTTP requests (Epic 8 will add `http_*` metrics — this epic only exposes whatever is already registered).
- Frontend consumption of the endpoints (Epic 7).
- Documentation pages under `docs/` beyond what's needed inline.

---

## Tasks

Each task is **one commit**. Run `make check` + `make test` before stopping. Stop after each task; wait for the user before starting the next.

| # | Task | Files | Status |
|---|------|-------|--------|
| 1 | API request/response Pydantic models | `quake/api/events/models.py` | ✅ |
| 2 | `EventsETL.query()` — combined-filter SQL + unit test | `database/etls/events.py`, `tests/unit/test_events_etl.py` | ✅ |
| 3 | Events Manager + Views scaffold + `/events/recent` route | `quake/api/events/{main,views}.py`, `quake/main.py`, `tests/unit/test_events_api_recent.py` | ✅ |
| 4 | `GET /events` combined-filter route + unit tests | `quake/api/events/views.py`, `tests/unit/test_events_api_query.py` | ✅ |
| 5 | `GET /metrics` endpoint | `quake/api/main/{main,views,models}.py`, `quake/api/main/__init__.py`, `tests/unit/test_main_api.py` | ✅ |
| 6 | `GET /env` endpoint | `quake/api/main/{main,views,models}.py`, `tests/unit/test_main_api.py` | ⬜ |
| 7 | Integration smoke — end-to-end through TestClient | `tests/integration/test_read_api.py` | ⬜ |

---

### Task 1 — API request/response Pydantic models ✅

**Outcome.**

Shipped as planned, no deviations. `quake/api/events/models.py` created with:

- `EventResponse` — mirrors `database.models.EventRow` (lines 31–46) minus `inserted_at`/`updated_at`. `ConfigDict(from_attributes=True)` set so `model_validate(row)` consumes an `EventRow` directly.
- `EventsListResponse` — `count: int` + `events: list[EventResponse]` envelope.
- `RecentEventsQuery` — `limit: int = Field(default=100, ge=1, le=1000)`.
- `EventsQuery` — all-optional combined query with the four filters + `limit`. Implements:
  - `@field_validator("near")` parsing `"lat,lon"` and enforcing the `[-90, 90]` / `[-180, 180]` ranges.
  - `@field_validator("since")` rejecting naive datetimes.
  - `@model_validator(mode="after")` enforcing `(near is None) == (radius_km is None)`.
  - `parsed_near` property returning `(lat, lon)` for downstream ETL use (Task 4).
- Module-level constants `_LIMIT_DEFAULT` / `_LIMIT_MIN` / `_LIMIT_MAX` were factored out so both query models share the same bounds — minor cosmetic decision inside the planned scope.

**Verification.** `make check` clean (isort, black, flake8, mypy, bandit, pyright). No unit tests in this task per spec; the models are exercised end-to-end by Tasks 3–4.

**Notes.** A docker hiccup during local testing was unrelated to the task content; resolved by a reboot before commit.

**Commit message (proposed).**

```
feat(api): add events request/response models

EventResponse mirrors EventRow minus internal timestamps; EventsQuery
parses near=lat,lon, validates ranges, requires near+radius_km together.
```

---

### Task 2 — `EventsETL.query()` combined-filter method ✅

**Outcome.**

Shipped as planned with one small additive deviation. Changes:

- `database/etls/events.py`: new `EventsETL.query(*, near, radius_km, min_magnitude, since, limit=100) -> list[EventRow]`. One SQL statement, `(%s::T IS NULL OR <condition>)` NULL-guard per filter. The whole geographic block (bounding-box pre-filter + inline haversine, reused from `near()`) is gated on `radius_km IS NULL`, so when `near` is omitted the bbox/haversine columns aren't evaluated at all.
- The method raises `ValueError` if exactly one of `near`/`radius_km` is supplied — defense-in-depth beyond the `EventsQuery` model validator, since `EventsETL` is also called directly from Celery tasks/scripts.
- `tests/unit/test_events_etl.py`: added the six planned tests (`test_query_no_filters_returns_recent`, `test_query_min_magnitude_only`, `test_query_since_only`, `test_query_near_only`, `test_query_combined`, `test_query_respects_limit`) plus one unplanned test (`test_query_partial_geo_args_raise`) covering the new `ValueError` guard.

**Deviation.** One extra test (`test_query_partial_geo_args_raise`) — a direct consequence of adding the ETL-level partial-args guard. Negligible scope creep but worth recording.

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 60 unit tests (7 new under `query`) + 1 integration.

**Commit message (proposed).**

```
feat(database): EventsETL.query for combined optional filters

Single-statement haversine + magnitude + since + limit, NULL-guarded
per parameter. Powers the upcoming GET /events read endpoint.
```

---

### Task 3 — Events Manager + Views scaffold + `/events/recent` ✅

**Outcome.**

Shipped as planned, no deviations. Changes:

- `quake/api/events/views.py` (new): `EventsManagerViews.recent(query: RecentEventsQuery = Depends()) -> EventsListResponse` — instantiates `EventsETL()` per request, calls `recent(query.limit)`, wraps rows in `EventResponse.model_validate(...)`.
- `quake/api/events/main.py` (new): `EventsManager` mirroring `MainManager` shape — `APIRouter(prefix="/events")`, `run()` registers `/recent` with `operation_id="events_recent"`, tag `Events`.
- `quake/main.py`: imports `EventsManager`, constructs it, mounts its router after `MainManager`.
- `tests/unit/test_events_api_recent.py` (new): the four planned tests. `client` fixture builds a `TestClient(Quake(logger).app)`; `events` fixture provides an `EventsETL` for seeding. Tests exercise newest-first ordering, `limit=2` honored, `limit=0 → 422`, empty-DB shape `{"count": 0, "events": []}`.

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 64 unit tests (4 new under `/events/recent`) + 1 integration. `events_recent` will appear under the `Events` tag in `/docs` (manual visual check; not asserted in a test per spec).

**Commit message (proposed).**

```
feat(api): wire GET /events/recent

Add EventsManager + Views, mount in quake/main.py, return paginated
EventsListResponse for the most recent N events.
```

---

### Task 4 — `GET /events` combined-filter route ✅

**Outcome.**

Shipped with one structural deviation that the planned tests forced. Changes:

- `quake/api/events/views.py`: added `EventsManagerViews.query(...)` that delegates to `EventsETL().query(near=query.parsed_near, ...)`. **Deviation:** the planned `query: EventsQuery = Depends()` binding produces 500s on `@field_validator` / `@model_validator` failures (they bypass FastAPI's request-validation pipeline). Switched both `recent` and `query` to `Annotated[Model, Query()]` — FastAPI's documented query-param-model pattern — so the planned 422 tests behave as specified. A short comment in the view docstring records the reasoning.
- `quake/api/events/main.py`: registered the `""` route on the `/events` router with `operation_id="events_query"`, tag `Events`.
- `tests/unit/test_events_api_query.py` (new): the eight planned tests — no-filter, near+radius, min_magnitude, since, all-four combined, partial-near 422, invalid-near-format 422, naive-since 422.

**Deviation summary.** Query-binding pattern changed from `Depends()` to `Annotated[Model, Query()]`. Mechanically required by the planned 422 tests; same pattern back-applied to `recent` for consistency. No new third-party dependency, no API-shape change for clients.

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 72 unit tests (8 new under `/events`) + 1 integration. `/docs` now shows both `events_recent` and `events_query` under the `Events` tag (manual check, not asserted).

**Commit message (proposed).**

```
feat(api): wire GET /events with combined optional filters

near=lat,lon + radius_km, min_magnitude, since, limit; all optional,
all combinable. Validation rejects partial near input and naive datetimes.
Switch query-param binding to Annotated[Model, Query()] so Pydantic
validator errors surface as 422 instead of unhandled 500s.
```

---

### Task 5 — `GET /metrics` endpoint ✅

**Outcome.**

Shipped with one small additive deviation. Changes:

- `quake/api/main/views.py`: added `metrics()` coroutine — `Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)`. No `make_asgi_app` sub-app; the route mounts uniformly with the others.
- `quake/api/main/main.py`: registered `/metrics` with `operation_id="main_metrics"`, tag `Main`.
- `quake/api/main/models.py`: untouched (raw text response).
- `quake/api/main/__init__.py`: **new content** — `from functions import celery_metrics` for side-effect registration on the default Prometheus registry. Module docstring documents the reason.
- `tests/unit/test_main_api.py` (new): `test_metrics_returns_prometheus_exposition` asserts 200, `text/plain` content-type, body contains `celery_task_total`.

**Deviation.** Plan assumed `functions.celery_metrics` was "already registered". It wasn't — that module was an orphan (no importer anywhere). Without an import path the API process's registry stays empty and the planned assertion fails. Added the side-effect import in `quake/api/main/__init__.py` (per-file-ignore for F401 already covers `__init__.py` in the project flake8 config). No client-visible behavior change; just the load hook the plan was missing.

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 73 unit tests (1 new for `/metrics`) + 1 integration.

**Commit message (proposed).**

```
feat(api): expose Prometheus /metrics endpoint

Surfaces the metric registry (currently populated by celery_metrics)
through MainManager. Epic 8 will add HTTP request metrics on top.
```

---

### Task 6 — `GET /env` endpoint

**Scope.**

- `quake/api/main/models.py`: new `EnvResponse(BaseModel)` — `environment: str`, `application_name: str`, `version: str`.
- `quake/api/main/views.py`: `env()` coroutine — returns `EnvResponse(environment=get_environmental_variables().environment.value, application_name=get_environmental_variables().application_name, version=__version__)`.
- `quake/api/main/main.py`: register `/env` route, `operation_id="main_env"`, tag `Main`.
- Extend `tests/unit/test_main_api.py` with `test_env_returns_current_environment` — request `/env`, assert keys + `environment == "testing"` (the sandbox conftest pins this).

**Acceptance.**

- `make check` clean.
- `make test` passes.

**Commit message (proposed).**

```
feat(api): expose GET /env with running environment summary

Returns ENVIRONMENT + APPLICATION_NAME + version for liveness and
provenance checks (complements /health).
```

---

### Task 7 — Integration smoke

**Scope.**

- New `tests/integration/test_read_api.py`:
  - Uses the integration conftest (sandbox DB on port 5436, dbmate-migrated).
  - Seeds a handful of events directly via `EventsETL.upsert_many` (no USGS call needed — this isolates the API surface from the ingestion path Epic 3 already covers).
  - Drives the `Quake` app via `TestClient` and asserts:
    - `/health` → 200, expected shape.
    - `/env` → 200, `environment == "testing"`.
    - `/metrics` → 200, contains `celery_task_total`.
    - `/events/recent?limit=2` → 200, two seeded events in correct order.
    - `/events?min_magnitude=5.0` → 200, only above-threshold rows.
    - `/events?near=37.0,23.0&radius_km=200` → 200, only nearby rows.
- One file, one test function per endpoint group is fine — the goal is wire-up verification, not exhaustive matrix coverage (unit tests already cover that).

**Acceptance.**

- `make check` clean.
- `make test` passes (the integration suite runs as part of `make test`; if not, the user is asked whether to add an `INTEGRATION=1` gate before stopping).

**Commit message (proposed).**

```
test(integration): end-to-end smoke for the read API

Spins the sandbox DB, seeds via EventsETL, drives the full FastAPI app
through TestClient, asserts every endpoint added in this epic.
```

---

## After all tasks ship

- User confirms commit range, then asks Claude to:
  - Mark Epic 4 ✅ Done in `MASTER_PLAN.md` with the commit range.
  - Archive this `PLAN.md` to `docs/history/epic-04-read-api.md` in one rename commit (user runs the git move; Claude only edits the file content if needed).
- Root `PLAN.md` slot is then free for Epic 5.
