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
| 1 | USGS HTTP client (`quake/ingestion/usgs/client.py`) | ✅ Done | `bb1c583` |
| 2 | GeoJSON parser + `EventRow` mapping (`quake/ingestion/usgs/parser.py`) | ✅ Done | `c2a2326` |
| 3 | Ingestion orchestrator (`quake/events/ingest.py`) | ⬜ Not started | — |
| 4 | Celery `poll_usgs` + Beat schedule + `health_check` (`quake/tasks.py`, `config.py`) | ⬜ Not started | — |
| 5 | Integration test (`tests/integration/test_poll_usgs.py`) | ⬜ Not started | — |

**Status legend:** `⬜ Not started` · `🟡 In progress` · `✅ Done`
**Next:** Task 3.

---

## Task 1 — USGS HTTP client ✅

**Status:** Done · Commit `bb1c583`

**Shipped** — 1 new module + 1 test module + 1 dep bump

### `quake/ingestion/usgs/client.py` (100 lines)
- **`UsgsFeed(StrEnum)`** — `ALL_HOUR = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"`. Adding day/week tiers is a one-line addition when needed.
- **`UsgsClient`** — sync context manager wrapping a long-lived `httpx.Client(timeout=10.0)`. Supports `with UsgsClient() as c:` via `__enter__`/`__exit__`; explicit `close()` too.
- **`UsgsClient._get(url)`** — `@tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)), reraise=True)`.
- **`UsgsClient.fetch(feed) -> dict[str, Any]`** — calls `_get`, post-validates the response:
  - Transport failure surviving all retries → wrapped as `UsgsClientError("unreachable…")` with `__cause__` chained to the httpx exception.
  - `response.status_code >= 400` → `UsgsClientError("…HTTP <code>…")` raised immediately (no retry).
  - Non-JSON body → `UsgsClientError("response was not valid JSON…")`.
  - Non-dict JSON (array, string, etc.) → `UsgsClientError("response was not a JSON object…")`.
- **`UsgsClientError(RuntimeError)`** — single typed exception for every USGS failure mode callers care about.

### `tests/unit/test_usgs_client.py` (78 lines)
4 tests, all green on first run, all respx-mocked (offline + deterministic):

| # | Test | Coverage |
|---|------|----------|
| 1 | `test_fetch_happy_path_returns_parsed_json` | 200 + JSON body round-trip; `route.call_count == 1` |
| 2 | `test_fetch_retries_transport_error_then_succeeds` | 2× `ConnectError` then 200; `call_count == 3`, body returned |
| 3 | `test_fetch_exhausts_retries_then_raises_usgs_client_error` | persistent `ConnectError` → `UsgsClientError(match="unreachable")` after `call_count == 3` |
| 4 | `test_fetch_http_4xx_raises_without_retry` | 400 → `UsgsClientError(match="400")` after `call_count == 1` (no retry) |

Autouse fixture patches `UsgsClient._get.retry.wait` to `tenacity.wait_none()` so the module completes in milliseconds rather than ~3s.

### `requirements-test.txt`
- Added `respx==0.23.1` (latest stable; ~30 KB, MIT-licensed). Verified via `pip show` — only adds zero new transitive deps beyond what httpx already pulls.

**Verifications**
- `make check` — clean (all 6 linters, 0 errors).
- `make test` — **39 passed in 5.56s** (35 existing + 4 new); no flakes; sandbox container cleaned up.

**Deviations from original plan**
1. **Retryable type narrowed from `httpx.HTTPError` → `(httpx.TransportError, httpx.TimeoutException)`.** Plan specified `httpx.HTTPError` as the retry trigger, but that's the base class of nearly every httpx exception, *including* `HTTPStatusError` (which `response.raise_for_status()` produces for 4xx). Using it would retry 4xx, directly contradicting the plan's other "4xx not retried" requirement. `TransportError` is the genuine "network failed" base class — exactly what we want to retry. The 4xx check now happens via `response.status_code` after the GET returns (which the retry decorator has already exited), so 4xx is never retried.
2. **Final-attempt failure wrapped as `UsgsClientError`.** Plan said `UsgsClientError` covers "HTTP 4xx (non-retryable) or after final-attempt failure", but `@tenacity.retry(..., reraise=True)` only re-raises the underlying httpx exception. Added a `try/except _RETRYABLE` in `fetch` to wrap it as `UsgsClientError("unreachable…")` with `__cause__` chained. Now callers can catch a single typed exception for every USGS failure mode.
3. **Extra defensive check: non-dict JSON.** USGS won't realistically return a JSON array or string, but the extra `isinstance(data, dict)` guard is one line and tightens the typed return contract (`dict[str, Any]`). Not tested explicitly.
4. **Test fixture uses `getattr(..., "retry")` to defeat mypy on tenacity's dynamic attribute.** tenacity attaches the `Retrying` instance as `.retry` on decorated functions at runtime, but the type stubs don't expose it; `getattr` returns `Any` and lets the monkeypatch land without any `# type: ignore`. Documented in the fixture docstring.

**Open follow-ups**
- (Carry-over) Pin `amacneil/dbmate` image to a specific version.
- (Carry-over) `pydantic-settings` still pinned but unused.
- (Carry-over) Decide on Dockerfile `build-essential` purge.
- (Carry-over) CI test-job docker pull warm-up (only if image-pull timeouts surface).

**Proposed commit message**
```
feat(ingestion): add USGS HTTP client with retry/backoff
```

---

## Task 2 — GeoJSON parser + `EventRow` mapping ✅

**Status:** Done · Commit `c2a2326`

**Shipped** — 1 new module + 1 captured fixture + 1 test module

### `quake/ingestion/usgs/parser.py` (88 lines)
- **`parse_feed(geojson: dict[str, Any]) -> list[EventRow]`** — pure transform. Iterates `geojson["features"]`, calls `_feature_to_row` per item, filters out `None` returns.
- **`_feature_to_row(feature, *, now)`** — private mapper. Returns `EventRow` or `None`.
  - **Required fields** (drop + log on miss): `id`, `properties.time`, `properties.mag`, `geometry.coordinates[0..1]` (lat/lon).
  - **Optional / nullable**: `magType`, `place`, `status`, `url`, `coordinates[2]` (depth — column is nullable).
  - **Type conversions**:
    - `time` (ms since epoch UTC) → `datetime.fromtimestamp(ms / 1000, tz=timezone.utc)`.
    - `tsunami` (int 0/1) → `bool`; missing → `False`.
  - `inserted_at` / `updated_at` set to a single `now = datetime.now(timezone.utc)` captured once per `parse_feed` call. DB defaults override on actual insert — placeholder lives with being throwaway.
- Logger via `setup_logger("usgs-parser", "quake-feed")` per the project pattern; WARNING-level when skipping.

### `tests/fixtures/usgs_all_hour.json`
Real USGS response captured from `all_hour.geojson` (6 features at capture time). Curl'd straight into the fixtures dir — no `/tmp` scratch.

### `tests/unit/test_usgs_parser.py` (104 lines)
7 tests, all green:

| # | Test | Coverage |
|---|------|----------|
| 1 | `test_parses_every_feature_in_fixture` | row count == feature count; all are `EventRow` |
| 2 | `test_round_trips_known_event` | spot-check on the first event: mag/magType/place/status/url/lon/lat/depth/time ms→datetime/tsunami int→bool |
| 3 | `test_skips_feature_missing_magnitude_and_keeps_the_rest` | drop one + log emitted; siblings unaffected |
| 4 | `test_skips_feature_missing_coordinates` | empty coords array → dropped |
| 5 | `test_handles_empty_feature_collection` | `{"features": []}` → `[]` |
| 6 | `test_handles_missing_features_key` | dict without `features` → `[]` (defensive) |
| 7 | `test_handles_missing_optional_depth` | 2-element coords (lat/lon only) → `depth_km is None` |

**Verifications**
- `make check` — clean (all 6 linters, 0 errors).
- `make test` — **46 passed in 5.68s** (39 existing + 7 new); no flakes.

**Deviations from original plan**
1. **Captured fixture is 6 features, not the "10–30" the plan suggested.** USGS had 6 events in the past hour when curl'd — pragmatic call to use whatever was live rather than synthesize extras. Tests use `len(fixture.features)` so they're independent of count.
2. **caplog assertion needed a `propagate=True` monkeypatch.** `setup_logger` sets `propagate=False` so its JSON handler is the sole production sink. pytest's `caplog` attaches at the root logger and can't see records from a non-propagating logger. The fix re-enables propagation **just for that one test** via `monkeypatch.setattr(logging.getLogger("usgs-parser"), "propagate", True)` — preserves the production design and respects the "no `# type: ignore` / no `# noqa`" rule. Documented in the test docstring.
3. **Three extra defensive tests** beyond the plan's three explicit scenarios: empty FeatureCollection, missing `features` key, missing optional depth. Cheap to write; pin behavior that's likely-good but not load-bearing.
4. **No `/tmp` scratch in the workflow.** Curl downloaded directly into `tests/fixtures/usgs_all_hour.json` (per the hygiene preference from Task 8 of Epic 2).
5. **User decision (mid-task):** keep the captured fixture (vs. fully inline synthetic dicts). Fixture earns its keep as schema documentation and as a real-USGS schema-drift detector.

**Open follow-ups**
Unchanged from Task 1.

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
