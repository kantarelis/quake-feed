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
| 1 | API request/response Pydantic models | `quake/api/events/models.py` | ⬜ |
| 2 | `EventsETL.query()` — combined-filter SQL + unit test | `database/etls/events.py`, `tests/unit/test_events_etl.py` | ⬜ |
| 3 | Events Manager + Views scaffold + `/events/recent` route | `quake/api/events/{main,views}.py`, `quake/main.py`, `tests/unit/test_events_api_recent.py` | ⬜ |
| 4 | `GET /events` combined-filter route + unit tests | `quake/api/events/views.py`, `tests/unit/test_events_api_query.py` | ⬜ |
| 5 | `GET /metrics` endpoint | `quake/api/main/{main,views,models}.py`, `tests/unit/test_main_api.py` | ⬜ |
| 6 | `GET /env` endpoint | `quake/api/main/{main,views,models}.py`, `tests/unit/test_main_api.py` | ⬜ |
| 7 | Integration smoke — end-to-end through TestClient | `tests/integration/test_read_api.py` | ⬜ |

---

### Task 1 — API request/response Pydantic models

**Scope.**

- New file `quake/api/events/models.py`.
- `EventResponse(BaseModel)` — public DTO for one event. Fields mirror `database.models.EventRow` minus `inserted_at` and `updated_at`. `ConfigDict(from_attributes=True)` so `EventResponse.model_validate(event_row)` works directly.
- `EventsListResponse(BaseModel)` — `count: int` + `events: list[EventResponse]`. Wrapping in an envelope leaves room for future fields (e.g. paging cursors) without breaking clients.
- `RecentEventsQuery(BaseModel)` — `limit: int` constrained to `1 <= limit <= 1000`, default `100`. Used as a dependency for `/events/recent`.
- `EventsQuery(BaseModel)` — all-optional combined query:
  - `near: str | None` (raw `"lat,lon"` string; parsed in a `@field_validator` into a `(lat, lon)` tuple, with range checks `-90 <= lat <= 90`, `-180 <= lon <= 180`).
  - `radius_km: float | None` (must be `> 0` and `<= 20_000`).
  - `min_magnitude: float | None` (typical range `-1.0 <= x <= 10.0`).
  - `since: datetime | None` (must be timezone-aware; reject naive datetimes in a `@field_validator`).
  - `limit: int` constrained to `1 <= limit <= 1000`, default `100`.
  - `@model_validator(mode="after")`: enforce `(near is None) == (radius_km is None)` — partial geographic input is a 422.

**Acceptance.**

- `make check` clean.
- No tests in this task (models are exercised by tasks 3–4).

**Commit message (proposed).**

```
feat(api): add events request/response models

EventResponse mirrors EventRow minus internal timestamps; EventsQuery
parses near=lat,lon, validates ranges, requires near+radius_km together.
```

---

### Task 2 — `EventsETL.query()` combined-filter method

**Scope.**

- Add `EventsETL.query(...)` to `database/etls/events.py`:
  - Signature: `query(self, *, near: tuple[float, float] | None = None, radius_km: float | None = None, min_magnitude: float | None = None, since: datetime | None = None, limit: int = 100) -> list[EventRow]`.
  - Single SQL statement with `(%s::float IS NULL OR <condition>)` NULL-guarded clauses for each optional filter. Reuses the bounding-box + haversine pattern already in `near()` when `near` is supplied.
  - Returns newest-first, capped at `limit`.
- Extend `tests/unit/test_events_etl.py`:
  - `test_query_no_filters_returns_recent` — three seeded events, no filters → all three, newest first.
  - `test_query_min_magnitude_only` — filters out below-threshold rows.
  - `test_query_since_only` — filters out rows older than `since`.
  - `test_query_near_only` — filters out rows outside the bounding-box / haversine radius.
  - `test_query_combined` — magnitude + since + near simultaneously, single matching row.
  - `test_query_respects_limit`.

**Acceptance.**

- `make check` clean.
- `make test` (which runs unit tests against the sandbox DB) passes the new tests.

**Commit message (proposed).**

```
feat(database): EventsETL.query for combined optional filters

Single-statement haversine + magnitude + since + limit, NULL-guarded
per parameter. Powers the upcoming GET /events read endpoint.
```

---

### Task 3 — Events Manager + Views scaffold + `/events/recent`

**Scope.**

- New `quake/api/events/main.py`: `EventsManager` with `router = APIRouter(prefix="/events")`, instantiates `EventsManagerViews`, `.run()` wires `/recent`.
- New `quake/api/events/views.py`: `EventsManagerViews` with one coroutine `recent(query: RecentEventsQuery = Depends())` that calls `EventsETL().recent(query.limit)` and returns `EventsListResponse(count=..., events=[EventResponse.model_validate(r) for r in rows])`.
- `quake/main.py`: import `EventsManager`, construct it, mount its router.
- New `tests/unit/test_events_api_recent.py`:
  - Helper to build a `TestClient` over the `Quake.app` (factory uses a stub logger).
  - `test_recent_returns_seeded_events_newest_first` — seed three rows with distinct times, call `/events/recent`, assert order + count.
  - `test_recent_respects_limit` — seed five rows, call `/events/recent?limit=2`, assert two rows.
  - `test_recent_rejects_invalid_limit` — `/events/recent?limit=0` → 422.
  - `test_recent_empty` — no rows, returns `{"count": 0, "events": []}`.

**Acceptance.**

- `make check` clean.
- `make test` passes; OpenAPI doc at `/docs` shows `events_recent` under the `Events` tag (manual verification only, no test).

**Commit message (proposed).**

```
feat(api): wire GET /events/recent

Add EventsManager + Views, mount in quake/main.py, return paginated
EventsListResponse for the most recent N events.
```

---

### Task 4 — `GET /events` combined-filter route

**Scope.**

- Add `EventsManagerViews.query(query: EventsQuery = Depends())` that calls `EventsETL().query(near=query.parsed_near, radius_km=query.radius_km, min_magnitude=query.min_magnitude, since=query.since, limit=query.limit)` and returns `EventsListResponse`.
- Wire route in `EventsManager.run()`: `""` path, `methods=["GET"]`, `operation_id="events_query"`, tag `Events`.
- New `tests/unit/test_events_api_query.py`:
  - `test_query_no_filters` — returns all seeded rows.
  - `test_query_near_and_radius` — only rows inside the circle.
  - `test_query_min_magnitude` — only rows at/above threshold.
  - `test_query_since` — only rows at/after timestamp.
  - `test_query_combined` — all four filters together, narrows to one row.
  - `test_query_partial_near_is_422` — `near=` without `radius_km=` → 422.
  - `test_query_invalid_near_format_is_422` — `near=not-a-coord` → 422.
  - `test_query_naive_since_is_422` — `since=2026-01-01T00:00:00` (no tz) → 422.

**Acceptance.**

- `make check` clean.
- `make test` passes; OpenAPI shows both `events_recent` and `events_query`.

**Commit message (proposed).**

```
feat(api): wire GET /events with combined optional filters

near=lat,lon + radius_km, min_magnitude, since, limit; all optional,
all combinable. Validation rejects partial near input and naive datetimes.
```

---

### Task 5 — `GET /metrics` endpoint

**Scope.**

- `quake/api/main/main.py`: register `/metrics` route on `MainManager.router`.
- `quake/api/main/views.py`: `metrics()` coroutine — returns `Response(content=prometheus_client.generate_latest(), media_type=prometheus_client.CONTENT_TYPE_LATEST)`. (Using `generate_latest` over `make_asgi_app` keeps the route mounting consistent with every other Manager endpoint — no special ASGI sub-app.)
- `quake/api/main/models.py`: no new model (raw text response).
- New `tests/unit/test_main_api.py`:
  - `test_metrics_returns_prometheus_exposition` — request `/metrics`, assert `200`, content-type starts with `text/plain`, body contains `celery_task_total` (registered at import time by `functions.celery_metrics`).

**Acceptance.**

- `make check` clean.
- `make test` passes.

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
