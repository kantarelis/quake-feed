# PLAN.md — Epic 2: Database layer (dbmate, baseline migration, ETL helpers)

> **Status:** Draft, awaiting user review.
> **Source epic:** [`MASTER_PLAN.md`](MASTER_PLAN.md) → Epic 2.
> **Lifecycle:** Tracked in git as the planned-vs-shipped audit trail for the active epic. Updated after each pushed commit per the [methodology in CLAUDE.md](CLAUDE.md#development-methodology--epic--planmd--tasks-one-task--one-commit). Archived to `docs/history/epic-02-database-layer.md` when the epic closes.

---

## Epic goal

The database layer is implemented end-to-end without any business logic on top of it:

1. **Schema** — A single `baseline.sql` dbmate migration creates the `quake` schema and every table the application needs (`events` as a TimescaleDB hypertable plus `event_revisions`, `alert_filters`, `api_keys`, `endpoint_locks`, `ingestion_runs`).
2. **Validation** — `make migrate-test` spins up a throwaway TimescaleDB on `:5433`, applies all migrations cold, rolls the newest back, re-applies. CI runs the same test against a service-container Postgres on every push.
3. **Runtime layer** — `database/main.py` exposes a typed connection pool, a `transaction()` context manager, and an `ExtractTransformLoad` base class with parameterized-SQL primitives.
4. **Typed shapes** — `database/models.py` defines a Pydantic model per row type.
5. **ETLs** — One `ExtractTransformLoad` subclass per table that has a write path in the app, each with focused unit tests against a real (sandboxed) DB.
6. **Schema dump** — `make db-schema` produces a tidy `database/schema.sql` via `database/_pretty_schema.py`.

**Out of scope.** USGS client, ingestion task, API endpoints, auth, alerts, frontend. The ETLs are wired and tested but no caller exercises them yet — that's Epics 3–6.

---

## Task ordering rationale

1. **Migration first.** Everything downstream consumes the schema. Until the migration exists, the connection layer, models, ETLs, and sandbox test have nothing to point at.
2. **Validate the migration immediately.** `make migrate-test` + CI integration land in the very next task so we never carry an unverified schema into ETL development.
3. **Connection layer + base ETL class** before models, so each subsequent ETL task can be a clean one-table commit (it inherits machinery rather than redefining it).
4. **Models** as a single typed-shapes commit, so ETLs in later tasks can return strongly typed rows without churn.
5. **ETLs grouped by domain**, smallest first: events+revisions (ingestion-side), then ingestion_runs (observability), then api_keys+alert_filters (auth/user-prefs). `endpoint_locks` gets a table in the migration but no ETL until Epic 5 needs one.
6. **Pretty-schema helper last** — it's a polish item that depends on the schema existing but blocks nothing.

---

## Progress

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | dbmate config + baseline migration | ✅ Done | _pending_ |
| 2 | Sandbox-test wiring (`make migrate-test` + CI job) | ⬜ Not started | — |
| 3 | Connection layer + `ExtractTransformLoad` base (`database/main.py`) | ⬜ Not started | — |
| 4 | Pydantic row models (`database/models.py`) | ⬜ Not started | — |
| 5 | Events + Revisions ETLs (`database/etls/events.py`, `database/etls/revisions.py`) | ⬜ Not started | — |
| 6 | Ingestion runs ETL (`database/etls/ingestion_runs.py`) | ⬜ Not started | — |
| 7 | API keys + Alert filters ETLs (`database/etls/api_keys.py`, `database/etls/alert_filters.py`) | ⬜ Not started | — |
| 8 | Pretty-schema helper (`database/_pretty_schema.py`) | ⬜ Not started | — |

**Status legend:** `⬜ Not started` · `🟡 In progress` · `✅ Done`
**Next:** Task 2.

---

## Task 1 — dbmate config + baseline migration ✅

**Status:** Done · Commit _pending_

**Shipped** — 2 new files
- `database/.dbmate.yml` — reference-only config. Pins `migrations_dir: ./database/migrations`, `schema_file: ./database/schema.sql`, `migrations_table_name: public.schema_migrations`. A comment in the file explains why the explicit `public.` qualifier matters (Postgres's default `search_path` against the `quake` DB user resolves the unqualified table name into the `quake` schema, which doesn't exist on first `dbmate up`). The Makefile still passes every flag explicitly per `CLAUDE.md` policy; this YAML is purely for editors/humans.
- `database/migrations/20260516170000_baseline.sql` — single dbmate migration containing both `-- migrate:up` and `-- migrate:down` blocks. `migrate:up` ships:
  - `CREATE EXTENSION IF NOT EXISTS timescaledb` + `CREATE SCHEMA IF NOT EXISTS quake`.
  - `quake.events` — every column the plan listed (`event_id`, `time`, `magnitude`, `magnitude_type`, `depth_km`, `latitude`, `longitude`, `place`, `status`, `tsunami`, `url`, `inserted_at`, `updated_at`) with `PRIMARY KEY (event_id, time)`. Followed by `SELECT create_hypertable('quake.events', 'time', if_not_exists => TRUE)` and two indexes (`magnitude`, `(latitude, longitude)`).
  - `quake.event_revisions` — append-only audit (`id BIGSERIAL PRIMARY KEY`, `event_id`, `observed_at`, `old_*`, `new_*` for magnitude / depth_km / place) with index on `(event_id, observed_at DESC)`.
  - `quake.api_keys` — hash-only registry (`id`, `key_hash UNIQUE`, `label`, `scopes TEXT[]`, `created_at`, `last_seen_at`, `revoked_at`).
  - `quake.alert_filters` — `api_key_id` FK with `ON DELETE CASCADE`, both bbox columns and center+radius columns (filter shape enforced application-side); index on `api_key_id`.
  - `quake.endpoint_locks` — `(lock_name TEXT PRIMARY KEY, is_locked BOOLEAN, locked_by, locked_at, reason)`; pre-seeded `INGESTION_LOCK` row via `INSERT ... ON CONFLICT DO NOTHING`.
  - `quake.ingestion_runs` — observability log with counts + error column and an index on `started_at DESC`.
  - **Revision trigger** — `quake.events_record_revision()` (PL/pgSQL) fires `AFTER UPDATE ON quake.events FOR EACH ROW`. Writes a row to `quake.event_revisions` when `|NEW.magnitude - OLD.magnitude| >= 0.1` OR `|NEW.depth_km - OLD.depth_km| >= 1.0` OR `NEW.place IS DISTINCT FROM OLD.place`. Thresholds inlined in the function body. `DROP TRIGGER IF EXISTS … ; CREATE TRIGGER …` so re-application is safe.
  - `migrate:down` drops trigger → function → tables in dependency-safe reverse order, finishing with `DROP SCHEMA quake CASCADE`.

**Verifications (all live, against a throwaway `timescale/timescaledb:latest-pg18` on `:5433`; dbmate run via the `amacneil/dbmate:latest` Docker image — no host-system installs)**
- `make check` clean (all six linters; pyright 0/0/0).
- `dbmate up`: applied the baseline in **31 ms**, no errors.
- `\dt quake.*`: all 6 tables present.
- `SELECT FROM timescaledb_information.hypertables`: confirms `quake.events` is a hypertable.
- `\df quake.*`: confirms `quake.events_record_revision` exists and returns `trigger`.
- Pre-seeded row: `SELECT * FROM quake.endpoint_locks` returns `INGESTION_LOCK` with `is_locked = false`.
- **Revision trigger exercised end-to-end** with 5 sequential UPDATEs on a seed event:
  - mag shift +0.05 → no revision ✓
  - mag shift +0.20 → revision row written ✓
  - depth shift +0.5 km → no revision ✓
  - depth shift +2.0 km → revision row written ✓
  - place change → revision row written ✓
  - Final count: exactly **3 revisions** matching the 3 threshold-crossing updates.
- `dbmate down`: rolled back in **47 ms**; `quake` schema gone from `information_schema.schemata`.
- `dbmate up` (re-apply): clean; all 6 tables back. Idempotency proven on the same DB instance.
- Throwaway container removed; no host-side leftovers.

**Deviations from original plan**
None of structural significance. Minor implementation choices the plan left open:

1. **Migration timestamp:** `20260516170000_baseline.sql` (today's date, 17:00 UTC). Arbitrary; chosen for readability.
2. **`OLD` values on revision rows reflect the row state at trigger-fire time.** Consecutive sub-threshold UPDATEs "build up" into the next `OLD` snapshot — e.g., the depth revision row shows `old_depth_km = 10.5` (the post-non-threshold value), not the seed's `10.0`. Standard `AFTER UPDATE FOR EACH ROW` semantics. Flagged in case you wanted "old" to mean "value before the most recent above-threshold change" (would require state tracking; more complex).
3. **Place changes are unconditional** (any non-equal text triggers a revision). Matches the plan's "any non-equal place"; revisit if USGS's trivial place reformulations turn out to be noisy.

**Proposed commit message**
```
feat(db): add baseline migration creating quake schema, tables, and revision trigger
```

---

## Task 2 — Sandbox-test wiring (Makefile + CI)

**Why now.** A migration we can't validate cold-start + rollback is a migration we don't trust.

**Files touched**
- `makefile` — fill in `migrate-test`. Approach: a shell recipe that
  1. starts a throwaway TimescaleDB container (`docker run -d --name quake_migrate_test ... -p 5433:5432 timescale/timescaledb:latest-pg18`),
  2. waits for `pg_isready` (with a 30 s timeout),
  3. runs `dbmate $(DBMATE_FLAGS) up` against `localhost:5433`,
  4. runs `dbmate $(DBMATE_FLAGS) down` (rolls back the newest migration),
  5. runs `dbmate $(DBMATE_FLAGS) up` again,
  6. tears the container down via `trap` so failures still clean up.
- `.github/workflows/code_quality_assurance.yml` — add a third job `migration-test`:
  - `needs: check` (per the sequential pattern set in Epic 1's CI review).
  - `services.postgres` = `timescale/timescaledb:latest-pg18` exposing `5432:5432` with `POSTGRES_USER/PASSWORD/DB` from env; healthcheck via `pg_isready`.
  - Steps: checkout → install `dbmate` (the Go binary, pinned version) → `dbmate up` → `dbmate down` → `dbmate up`, all with explicit `DATABASE_URL` and `--migrations-table public.schema_migrations`.

**Acceptance**
- `make migrate-test` exits 0 on a clean machine (no leftover container even after failure).
- The new CI job runs and goes green on a test push.
- `make check` clean.

**Proposed commit message**
```
ci(db): wire sandbox migrate-test target and CI job for migrations
```

---

## Task 3 — Connection layer + `ExtractTransformLoad` base

**Why now.** Every ETL inherits from this; build the foundation before the consumers.

**Files created**
- `database/main.py` — three things:
  - `_get_pool()` — lazy singleton `psycopg.ConnectionPool` built from `get_environmental_variables().database`. `min_size=1, max_size=10`. Closes on shutdown (registered via `atexit` for the process).
  - `@contextmanager transaction()` — yields a `psycopg.Connection` checked out of the pool, commits on clean exit, rolls back on exception, returns the connection to the pool in `finally`.
  - `class ExtractTransformLoad` — base class with two protected helpers:
    - `_execute(sql: str, params: tuple | None = None, *, fetch: Literal["one", "all", "none"] = "none") -> Any` — opens a `transaction()`, runs the cursor, returns rows or `None`.
    - `_executemany(sql: str, rows: Iterable[tuple]) -> int` — batch insert/update; returns affected row count.
    - Subclasses store any per-table config (table name, default columns) and expose typed methods on top. No magic.

**Acceptance**
- `python -c "from database.main import transaction, ExtractTransformLoad; print('OK')"` succeeds.
- Smoke test (manual): `with transaction() as conn: conn.execute('SELECT 1')` returns the expected row against the running compose DB.
- `make check` clean.

**Proposed commit message**
```
feat(db): add connection pool, transaction() context manager, and ExtractTransformLoad base
```

---

## Task 4 — Pydantic row models

**Why now.** Models are tiny but blocking — every ETL returns one.

**Files created**
- `database/models.py` — one Pydantic `BaseModel` per row type, mirroring the migration columns exactly. Camel-vs-snake: snake everywhere; `from_attributes = True` on the configs so they accept `psycopg` row-dict access patterns.
  - `EventRow` — every column of `quake.events`.
  - `EventRevisionRow` — every column of `quake.event_revisions`.
  - `ApiKeyRow` — every column of `quake.api_keys` **except** the raw key (it never lives in the row model; only the hash does).
  - `AlertFilterRow`, `EndpointLockRow`, `IngestionRunRow` — same pattern.
  - `models/events.py`, `models/alerts.py` (the higher-level domain models that consumers use) stay deferred to later epics; this file is row-shape only.

**Acceptance**
- `from database.models import EventRow, EventRevisionRow, ApiKeyRow, AlertFilterRow, EndpointLockRow, IngestionRunRow` succeeds.
- Pydantic forbids extra fields (pydantic-mypy default from setup.cfg) — verified by attempting to instantiate one with a bogus kwarg and catching `ValidationError`.
- `make check` clean (pydantic-mypy validates field types statically).

**Proposed commit message**
```
feat(db): add Pydantic row models for every quake.* table
```

---

## Task 5 — Events + Revisions ETLs

**Why now.** Largest single behavior surface; revisions depend on events; tightly coupled and best landed together.

**Files created**
- `database/etls/events.py` — `EventsETL(ExtractTransformLoad)`:
  - `upsert(event: EventRow) -> Literal["inserted", "updated", "unchanged"]` — `INSERT ... ON CONFLICT (event_id, time) DO UPDATE SET ...` returning the row state. The revision trigger handles history; the ETL just performs the write.
  - `upsert_many(events: Iterable[EventRow]) -> dict[str, int]` — batched UPSERT returning counts of `{inserted, updated}`.
  - `get_by_id(event_id: str) -> EventRow | None` — single-row lookup keyed on the most recent `time` for that `event_id`.
  - `recent(limit: int) -> list[EventRow]` — `ORDER BY time DESC LIMIT %s`.
  - `by_magnitude(min_magnitude: float, since: datetime | None = None) -> list[EventRow]`.
  - `near(lat: float, lon: float, radius_km: float) -> list[EventRow]` — naive bounding-box pre-filter + haversine fallback in SQL.
- `database/etls/revisions.py` — `RevisionsETL(ExtractTransformLoad)`:
  - `for_event(event_id: str) -> list[EventRevisionRow]` — `ORDER BY observed_at DESC`.
  - `recent(limit: int) -> list[EventRevisionRow]`.
  - No write methods — revisions are inserted by the DB trigger.
- `tests/unit/test_events_etl.py` — async tests using the existing sandbox container or a fixture:
  - upsert of a new event returns `"inserted"`.
  - upsert of the same `(event_id, time)` with same magnitude returns `"unchanged"` (or `"updated"` — pick once and stick; design decision in implementation).
  - upsert with magnitude shift ≥ 0.1 writes exactly one row to `event_revisions` (cross-check via `RevisionsETL.for_event`).
  - `recent(5)` returns events in `time DESC` order.
- `tests/conftest.py` (extended) — fixture that yields a connection scoped to a transaction that always rolls back, so tests don't pollute each other.

**Acceptance**
- All new tests pass via `pytest tests/unit/test_events_etl.py -v` against the running compose DB (assume the operator runs `make up` first; document that in the test module's top docstring).
- `make check` clean.
- `make test` runs the new tests (the no-tests-collected wrapper is no longer triggered — there are actual tests now).

**Proposed commit message**
```
feat(db): add Events and Revisions ETLs with parameterized SQL and unit tests
```

---

## Task 6 — Ingestion runs ETL

**Why now.** Small, observability-only, no coupling to other ETLs — a clean isolated commit.

**Files created**
- `database/etls/ingestion_runs.py` — `IngestionRunsETL(ExtractTransformLoad)`:
  - `start_run() -> int` — `INSERT (started_at) VALUES (now()) RETURNING id`.
  - `finish_run(run_id: int, *, inserted: int, updated: int, revisions: int, error: str | None = None) -> None`.
  - `latest(limit: int) -> list[IngestionRunRow]`.
- `tests/unit/test_ingestion_runs_etl.py` — start → finish → assert row state and counts.

**Acceptance**
- New tests green. `make check` clean.

**Proposed commit message**
```
feat(db): add IngestionRuns ETL for per-poll observability records
```

---

## Task 7 — API keys + Alert filters ETLs

**Why now.** The two auth-side ETLs are small and conceptually paired (a filter belongs to a key). Single commit.

**Files created**
- `database/etls/api_keys.py` — `ApiKeysETL(ExtractTransformLoad)`:
  - `insert(key_hash: str, label: str | None, scopes: list[str]) -> int` — returns the new row's `id`.
  - `get_by_hash(key_hash: str) -> ApiKeyRow | None`.
  - `touch_last_seen(api_key_id: int) -> None` — `UPDATE ... SET last_seen_at = now()`.
  - `revoke(api_key_id: int) -> None` — `UPDATE ... SET revoked_at = now()`.
  - **Never stores or returns raw keys.** Hashing happens in the caller (Epic 5); this layer is hash-in / hash-out.
- `database/etls/alert_filters.py` — `AlertFiltersETL(ExtractTransformLoad)`:
  - `upsert(filter: AlertFilterRow) -> int` — keyed on `(api_key_id, id)`.
  - `for_api_key(api_key_id: int) -> list[AlertFilterRow]`.
  - `delete(filter_id: int, api_key_id: int) -> bool` — returns whether a row was removed (defensive against cross-key deletion).
- `tests/unit/test_api_keys_etl.py` + `tests/unit/test_alert_filters_etl.py` — round-trip insert/get/update/delete for each.

**Acceptance**
- New tests green. `make check` clean.

**Proposed commit message**
```
feat(db): add ApiKeys and AlertFilters ETLs
```

---

## Task 8 — Pretty-schema helper

**Why last.** Polish; depends on the schema existing but blocks nothing.

**Files created / modified**
- `database/_pretty_schema.py` — module that:
  - Reads `database/schema.sql` (produced by `dbmate dump`).
  - Strips noise (comments dbmate emits, `SET` statements that mirror the user's session).
  - Re-orders blocks: `CREATE SCHEMA` → extensions → tables (alphabetical) → indexes → functions → triggers → seed inserts.
  - Writes the cleaned-up output back in place.
- `makefile` — change `db-schema` target to: `dbmate dump` → `python -m database._pretty_schema` → done.

**Acceptance**
- `make db-schema` against the running compose DB produces a stable, re-runnable `database/schema.sql` (running twice in a row gives the same bytes).
- `database/schema.sql` is still gitignored (per `.gitignore` from Epic 1) — verify with `git check-ignore -v database/schema.sql`.
- `make check` clean (the helper itself is Python and lint-checked).

**Proposed commit message**
```
chore(db): add _pretty_schema.py and wire it into make db-schema
```

---

## Open questions to settle before Task 1

1. **Hypertable PK choice.** Plan above uses `PRIMARY KEY (event_id, time)`. The alternative is to make `events` a **non-hypertable** with `PRIMARY KEY (event_id)` and just an index on `time`. The hypertable buys time-bucketed compression/retention later; the PK pattern adds a tiny upsert quirk (USGS time revisions for the same `event_id` would create duplicate rows). Sticking with hypertable unless you'd rather not.
2. **Revision logic — trigger vs. application.** Plan uses a DB trigger because `CLAUDE.md` says thresholds are "defined in a migration". The alternative is to delete the trigger and have the events ETL do `SELECT old → compare → INSERT revision IF needed → UPDATE event` inside a single transaction. Trigger is less code, application-level is more visible. Trigger is my default; flag if you want to swap.
3. **Noise thresholds.** I've drafted `magnitude_delta ≥ 0.1` and `depth_delta ≥ 1.0 km`. Reasonable starting points but worth a sanity check from your seismology side.
4. **Test DB strategy.** Tasks 5–7 assume tests run against the live compose DB with per-test transactional rollback. Alternative: each test class spins up its own throwaway container (slower; cleaner isolation). The compose-DB pattern matches Epic 1's "local-only" posture; flag if you'd prefer the per-test container approach.
5. **`endpoint_locks` table — no ETL in Epic 2.** Plan creates the table now and adds the ETL in Epic 5 when the admin locks endpoint actually consumes it. Leave it as-is, or land an `EndpointLocksETL` here for completeness?
6. **`pydantic-settings` cleanup.** Carry-over open follow-up from Epic 1; might as well drop it from `requirements.txt` in Task 3 (where we're touching the data layer dependencies anyway). Want me to fold that in?

---

## Workflow reminder

After each task: I run `make check` + `make test`, then stop with a summary and a proposed commit message. **I do not run `git add`, `git commit`, or `git push`.** You review the diff, commit, push, and prompt me for the next task.
