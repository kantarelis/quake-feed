# PLAN.md — Epic 3: USGS ingestion worker

> **Status:** Draft, awaiting user review.
> **Source epic:** [`MASTER_PLAN.md`](MASTER_PLAN.md) → Epic 3.
> **Lifecycle:** Tracked in git as the planned-vs-shipped audit trail for the active epic. Updated after each pushed commit per the [methodology in CLAUDE.md](CLAUDE.md#development-methodology--epic--planmd--tasks-one-task--one-commit). Archived (or emptied) when the epic closes.

---

## Epic goal

Every 60 seconds the Celery worker:

1. **Fetches** the USGS realtime earthquake feed (GeoJSON over HTTPS) with retries/backoff.
2. **Parses** each Feature into an `EventRow` via a pure function.
3. **Upserts** the batch through `EventsETL.upsert_many` — the `events_revision_trigger` from Epic 2 handles revision rows automatically when magnitude/depth/place thresholds are crossed.
4. **Records** the run in `quake.ingestion_runs` with `(started_at, finished_at, inserted_count, updated_count, revision_count, error?)` via `IngestionRunsETL`.

A separate `health_check` task pings the DB for liveness checks.

**Out of scope.** API endpoints, auth, SSE alerts, frontend, Prometheus metric definitions, Grafana dashboards. We are producing data into the schema Epic 2 created; reads happen in Epics 4–6 and observability lands in Epic 8.

---

## Task ordering rationale

1. **Client first.** Pure network I/O. Mock-testable, no DB dependency — lowest-risk first.
2. **Parser / mapper second.** Pure function from raw GeoJSON dict to `list[EventRow]`. Pairs naturally with a captured fixture; still no DB.
3. **Orchestrator third.** First DB-touching code in the epic — glues client → parser → `EventsETL` → `IngestionRunsETL`. Tested against the session-scoped sandbox DB from Epic 2's conftest.
4. **Celery task + Beat schedule + health check fourth.** Thin wrapper that registers the orchestrator as a Beat-scheduled task. Defers Celery wiring until the underlying function is proven.
5. **Integration test last.** End-to-end smoke against the live compose stack — depends on everything else and on the operator having `make up` running.

---

## Progress

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | USGS HTTP client (`quake/ingestion/usgs/client.py`) | ⬜ Not started | — |
| 2 | GeoJSON parser + `EventRow` mapping (`quake/ingestion/usgs/parser.py`) | ⬜ Not started | — |
| 3 | Ingestion orchestrator (`quake/events/ingest.py`) | ⬜ Not started | — |
| 4 | Celery `poll_usgs` + Beat schedule + `health_check` (`quake/tasks.py`, `config.py`) | ⬜ Not started | — |
| 5 | Integration test (`tests/integration/test_poll_usgs.py`) | ⬜ Not started | — |

**Status legend:** `⬜ Not started` · `🟡 In progress` · `✅ Done`
**Next:** Task 1.

---

## Task 1 — USGS HTTP client

**Why now.** Lowest-risk isolated piece. Validates the `httpx` + `tenacity` wiring (both already pinned in `requirements.txt`) before anything depends on it.

**Files created**
- `quake/ingestion/__init__.py` and `quake/ingestion/usgs/__init__.py` — empty package markers.
- `quake/ingestion/usgs/client.py`:
  - `class UsgsFeed(StrEnum)` — feed tiers we care about. Initial entry: `ALL_HOUR = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"`. Adding `ALL_DAY` / `ALL_WEEK` is one line each when needed.
  - `class UsgsClient`:
    - `__init__(self, timeout: float = 10.0)` — builds a long-lived `httpx.Client`.
    - `fetch(self, feed: UsgsFeed) -> dict` — HTTP GET, parse JSON, return dict.
    - Retry wrapper: `@tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)), reraise=True)`.
    - `close(self) -> None` and `__enter__`/`__exit__` so callers can use `with UsgsClient() as c:`.
  - `class UsgsClientError(RuntimeError)` — raised for HTTP 4xx (non-retryable) or after final-attempt failure.
- `tests/unit/test_usgs_client.py`:
  - **Happy path** — mock `httpx.Client.get` to return a 200 with `{"type": "FeatureCollection", "features": []}`; assert the dict round-trips.
  - **Retry-then-succeed** — mock raises `httpx.ConnectError` twice, then succeeds. Assert the result returns and call count == 3.
  - **Final failure** — mock always raises; assert it raises after 3 attempts.
  - **HTTP 4xx** — mock returns 400; assert `UsgsClientError` (not retried).
  - Uses `respx` for httpx mocking (one new test-dep — alternative is `unittest.mock` on the client method).

**Acceptance**
- `make check` clean (note: `httpx`, `tenacity` already typed; `respx` if added needs `ignore_missing_imports` check).
- New tests pass; total test count is 35 (existing) + 4 = 39.

**Proposed commit message**
```
feat(ingestion): add USGS HTTP client with retry/backoff
```

---

## Task 2 — GeoJSON parser + `EventRow` mapping

**Why now.** Pure function, no I/O, no DB. Pairs naturally with a captured USGS response fixture so the test stays deterministic and offline-friendly.

**Files created**
- `quake/ingestion/usgs/parser.py`:
  - `def parse_feed(geojson: dict) -> list[EventRow]` — pure transform from a USGS FeatureCollection dict to a list of `EventRow` instances.
  - **USGS schema mapping** (per Feature):
    | `EventRow` field | USGS source |
    |---|---|
    | `event_id` | `feature["id"]` |
    | `time` | `datetime.fromtimestamp(feature["properties"]["time"] / 1000, tz=UTC)` (USGS gives ms since epoch UTC) |
    | `magnitude` | `properties["mag"]` |
    | `magnitude_type` | `properties["magType"]` |
    | `depth_km` | `geometry["coordinates"][2]` |
    | `latitude` | `geometry["coordinates"][1]` |
    | `longitude` | `geometry["coordinates"][0]` |
    | `place` | `properties["place"]` |
    | `status` | `properties["status"]` |
    | `tsunami` | `bool(properties["tsunami"])` (USGS uses int 0/1) |
    | `url` | `properties["url"]` |
    | `inserted_at`, `updated_at` | `datetime.now(timezone.utc)` (placeholder — DB defaults override on actual insert) |
  - **Skip-and-warn-log** any Feature missing required fields (`id`, `properties.time`, `properties.mag`, `geometry.coordinates[0..2]`). Drop that feature, continue with the rest.
- `tests/fixtures/usgs_all_hour.json` — captured USGS response (`curl … > tests/fixtures/usgs_all_hour.json`). 10–30 features is plenty.
- `tests/unit/test_usgs_parser.py`:
  - Loads the fixture, asserts `len(parse_feed(...)) == fixture.features.length` (minus any intentionally-malformed entries).
  - Spot-checks 1–2 specific events for round-trip correctness (magnitude, time conversion ms→datetime, lat/lon order, tsunami int→bool).
  - **Skip-malformed** — feed with one feature missing `properties.mag` → that feature dropped, others kept, log emitted.

**Acceptance**
- `make check` clean.
- New tests pass.

**Proposed commit message**
```
feat(ingestion): parse USGS GeoJSON into EventRow batches
```

---

## Task 3 — Ingestion orchestrator

**Why now.** First DB-touching code in the epic. Validates the client + parser + ETL chain end-to-end before Celery comes into play.

**Files created**
- `quake/events/__init__.py` — empty package marker.
- `quake/events/ingest.py`:
  - `class IngestionResult(BaseModel)` — typed return: `inserted: int`, `updated: int`, `revisions: int`, `error: str | None = None`.
  - `def poll_once(client: UsgsClient | None = None, feed: UsgsFeed = UsgsFeed.ALL_HOUR) -> IngestionResult`:
    1. Open the run: `run_id = IngestionRunsETL().start_run()`. Capture `run_started = datetime.now(timezone.utc)` for the revision count window.
    2. `try:`
       - `client = client or UsgsClient()` (caller-supplied for tests).
       - `raw = client.fetch(feed)`.
       - `events = parse_feed(raw)`.
       - `counts = EventsETL().upsert_many(events)` → `{inserted, updated}`.
       - `revisions = SELECT count(*) FROM quake.event_revisions WHERE observed_at >= %s` (param: `run_started`).
       - `IngestionRunsETL().finish_run(run_id, inserted=counts["inserted"], updated=counts["updated"], revisions=revisions)`.
       - Return `IngestionResult(inserted=..., updated=..., revisions=...)`.
    3. `except Exception as exc:` capture `str(exc)`, `finish_run(run_id, inserted=0, updated=0, revisions=0, error=str(exc))`, then re-raise.
- `tests/unit/test_ingest.py`:
  - **Happy path** — monkeypatch `UsgsClient.fetch` to return the Task 2 fixture; run `poll_once()`; assert events landed in `quake.events`, ingestion_runs row complete, `IngestionResult.inserted == fixture.feature_count`, `revisions == 0` (fresh DB).
  - **Idempotent re-run** — call `poll_once()` twice; second call yields `updated == feature_count` and `inserted == 0`.
  - **Revision** — first call inserts; mutate the fixture's first feature's `mag` by +0.3, second call → `revisions == 1`.
  - **Error path** — monkeypatch `UsgsClient.fetch` to raise; assert ingestion_runs row records the error and `poll_once` re-raises.

**Acceptance**
- `make check` clean.
- New tests pass against the session-scoped sandbox DB.

**Proposed commit message**
```
feat(ingestion): orchestrate USGS poll → upsert → ingestion-run record
```

---

## Task 4 — Celery task + Beat schedule + health check

**Why now.** Final wiring step — depends on the orchestrator being callable and tested.

**Files created / modified**
- `config.py` (modified) — Celery app already exists from Epic 1. Add a Beat schedule:
  ```python
  celery_app.conf.beat_schedule = {
      "poll_usgs_every_60s": {
          "task": "quake.tasks.poll_usgs",
          "schedule": 60.0,
      },
  }
  ```
- `quake/tasks.py` (new):
  - `@celery_app.task(name="quake.tasks.poll_usgs", bind=True, max_retries=0) def poll_usgs(self) -> dict:` — calls `quake.events.ingest.poll_once()`, returns `result.model_dump()`. `max_retries=0` because retries belong inside the HTTP client; Celery-level retry would double-retry.
  - `@celery_app.task(name="quake.tasks.health_check") def health_check() -> dict:` — `with transaction() as conn: conn.execute("SELECT 1")`; returns `{"status": "ok", "ts": now_iso}`.
- `tests/unit/test_tasks.py`:
  - `poll_usgs` returns the expected dict — monkeypatch `UsgsClient.fetch` to the fixture, invoke `poll_usgs.apply().get()`.
  - `health_check` returns `{"status": "ok"}` against the sandbox DB.
  - (Beat schedule itself isn't unit-tested; it's a config dict.)

**Acceptance**
- `make check` clean.
- New tests pass.
- Manual smoke (documented in the test module's top docstring): `make up` then `docker compose exec backend celery -A config inspect registered` shows both tasks.

**Proposed commit message**
```
feat(ingestion): wire poll_usgs and health_check Celery tasks
```

---

## Task 5 — Integration test

**Why last.** End-to-end smoke; depends on every preceding task and on the operator having `make up` running.

**Files created / modified**
- `tests/integration/test_poll_usgs.py`:
  - `@pytest.mark.integration` on every test in the module.
  - One end-to-end test: synchronously invoke `poll_usgs.apply().get()` against the live compose DB (already migrated), assert `>=1` row landed in `quake.events`, assert the latest `ingestion_runs` row has `finished_at IS NOT NULL` and `error IS NULL`.
  - Hits **real USGS** (not mocked) — see open question.
- `makefile` (modified): add a `test-integration:` target running `$(PYTEST) -m integration tests/integration/` and skip the marker by default in `make test` (the `pytest.ini` `markers` block already declares the marker; default `make test` doesn't filter by marker, but integration tests are *gated by `make up`* — needs a separate make target to invoke deliberately).
  - Concrete: change the default `test` target to `$(PYTEST) -m "not integration"` so plain `make test` keeps running only unit tests; `make test-integration` opts in.

**Acceptance**
- `make test-integration` passes against the running stack (real USGS).
- `make test` (unit-only) still passes 35 + Tasks 1–4 tests without touching USGS.

**Proposed commit message**
```
test(ingestion): integration smoke for poll_usgs against the live stack
```

---

## Open questions to settle before Task 1

1. **USGS feed tier.** `all_hour.geojson` (60-minute window, refreshed every 60s) matches our poll cadence; `all_day` is heavier but more forgiving of a missed poll. Sticking with `all_hour` unless you'd rather not.
2. **`respx` for httpx mocking?** Adds one test-dep (~30 KB, MIT). Alternative is `unittest.mock.patch` on the client method — works fine but is less idiomatic. Default: `respx`.
3. **`inserted_at` / `updated_at` on parsed `EventRow`.** Both are required NOT NULL columns. Parser sets them to `datetime.now(timezone.utc)`; DB defaults override on actual insert anyway. Alternative would be to make them nullable in the row model — pollutes the read shape. Default: parser sets the placeholder, lives with it being throwaway.
4. **Skip-malformed vs. fail-fast on a bad Feature?** Currently planned: skip the bad feature, log a warning, continue. Alternative: raise on the first malformed entry. Default: skip-and-log — USGS occasionally emits weird outliers and we'd rather lose one event than lose the whole batch.
5. **Endpoint-lock honoring.** `quake.endpoint_locks.INGESTION_LOCK` is pre-seeded but `EndpointLocksETL` was deferred to Epic 5. Wire the lock check in this epic now, or wait for Epic 5? Default: wait. Add a one-line `SELECT is_locked` check now if you want the kill switch active before Epic 5 lands.
6. **Beat cadence.** Plan says 60s. USGS refreshes the `all_hour` feed every 60s; matching cadence is correct. No change proposed.
7. **Integration test against real USGS vs. recorded playback?** Real USGS is more realistic but flaky if the last hour returned 0 events (rare). Recorded `respx` playback is deterministic but it stops being a real *integration* test. Default: real USGS, with the test marked `@pytest.mark.xfail(strict=False)` only if a 0-event hour proves to be a real problem.
8. **Where does `models/events.py` (mentioned in `CLAUDE.md`) fit?** Plan envisioned a domain `Event` model wrapping `EventRow`. For Epic 3 the parser produces `EventRow` directly (no wrapping); the domain model only earns its keep when the API layer needs to project a different shape. Default: defer `models/events.py` to Epic 4 when the read API needs it.

---

## Workflow reminder

After each task: I run `make check` + `make test`, then stop with a summary and a proposed commit message. **I do not run `git add`, `git commit`, or `git push`.** You review the diff, commit, push, and prompt me for the next task.
