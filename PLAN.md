# PLAN.md — Epic 6: SSE alerts (`/alerts/stream`)

**Status:** 🟡 In progress
**Epic source:** [`MASTER_PLAN.md`](MASTER_PLAN.md) — Epic 6
**Branch:** new feature branch off `kantarelis` (PRs target `kantarelis`)

---

## Goal

Ship the realtime-alerts surface:

- **Persistent per-key filters** managed via authenticated CRUD on `/alerts/filters` (GET/POST/PATCH/DELETE). Backed by the existing `quake.alert_filters` table and `AlertFiltersETL` (already shipped in Epic 2).
- **In-process matcher** (`quake/alerts/matcher.py`) that decides whether a given event matches a given filter.
- **In-process pub/sub** (`quake/alerts/registry.py`) — every connected SSE client has a slot holding a snapshot of their filters and an asyncio queue. New events get matched against every active subscriber's filters and pushed into queues whose filter matches.
- **Worker → API channel** via Postgres `LISTEN`/`NOTIFY`. A Postgres trigger on `quake.events` (INSERT only) calls `pg_notify('quake_event_inserts', to_jsonb(NEW))`. The API process owns a background `AlertListener` task started in the FastAPI lifespan that LISTENs on that channel, decodes the JSON, and hands the event to the in-process registry.
- **`/alerts/stream`** — `sse-starlette` `EventSourceResponse` that authenticates, snapshots this key's filters, subscribes to the registry, yields matching envelopes as SSE events, and cleans up on disconnect.
- **`docs/alerts.md`** — design note: the LISTEN/NOTIFY hop, the in-process matcher, filter semantics, the single-pod limit.

## Design choices (locked up-front so tasks don't re-litigate)

1. **Worker → API transport: Postgres `LISTEN`/`NOTIFY` on a DB trigger.** Celery and the API run in separate OS processes; an "in-process queue" between them is impossible without a hop. Postgres is already in the stack and ships native pub/sub with sub-millisecond fanout. A trigger on `quake.events` INSERT calls `pg_notify('quake_event_inserts', to_jsonb(NEW)::text)`. Zero new infrastructure, zero changes to `EventsETL.upsert_many` or `poll_once`.
2. **Single channel, INSERT-only.** V1 fires on new events only. UPDATEs (USGS refinements) are observable through `event_revisions` and out of scope here — adding them is a future epic if the use case shows up. Keeps the matcher's input domain simple (one envelope shape, no "this is an update of an existing event you saw five minutes ago" semantics).
3. **Filter combination is OR within an API key.** A subscriber's snapshot is `list[AlertFilter]`; an event matches if it matches ANY filter. Matches an obvious mental model (the user adds filters meaning "also alert me on this") and avoids forcing the user to encode intersections via a single overloaded row.
4. **Filter shape: bbox XOR center+radius.** Mirrors the DB column groups already in `quake.alert_filters`. Enforced application-side via Pydantic validator on the input DTO; the DB stays accommodating. `min_magnitude` is optional and combinable with either shape.
5. **`SubscriberRegistry` is a module-level singleton in the API process.** No DI for it — it's a global per-process bus, like the prom collector. Tests reach in via a fixture that resets it between cases.
6. **Filter snapshot is taken at connect time.** If the client edits their filters mid-stream, the SSE connection keeps using the old snapshot until they reconnect. Documented in `docs/alerts.md`. Removes the need for a registry-side invalidation channel; client reconnect is the refresh primitive.
7. **`AlertListener` runs as one background task per API process, started in the FastAPI lifespan.** Pure async via psycopg's async LISTEN support. On shutdown, the task is cancelled cleanly. If the listener crashes, the lifespan logs and restarts it (single-supervisor loop in `quake/alerts/listener.py`).
8. **Filter CRUD is per-key scoped.** Every CRUD route reads/writes against `AlertFiltersETL` with `api_key_id` from the authenticated `ApiKeyRow`. The ETL already enforces this in its WHERE clauses (Epic 2 shipped); the views inherit that guarantee.
9. **SSE event format.** One event type, `event: alert`, JSON-encoded `AlertEnvelope`. `sse-starlette`'s default keep-alive ping is sufficient — no custom heartbeat. `retry: 5000` (5s) so clients reconnect on transient drops.
10. **Test pattern.** Unit tests use the registry + matcher directly; the SSE endpoint test reads a few events from `httpx`'s streaming response then closes the connection. The listener gets its own unit test against the sandbox DB (real `LISTEN`/`NOTIFY`, real trigger). One integration test wires the full path — worker `INSERT` → trigger NOTIFY → API listener → registry → SSE client.

## Out of scope

- UPDATE / revision events on the SSE stream (INSERT-only V1 — see decision 2).
- Cross-pod fanout. Single-pod by design per the MASTER_PLAN constraint; documented in `docs/alerts.md`.
- A WebSocket variant of `/alerts/stream`. SSE is sufficient for a one-way push.
- Per-filter rate limiting / cooldown windows.
- "Mute this filter for 24h" semantics. If a filter is too noisy the client edits or deletes it.
- Bulk-create filters via a single POST. POST takes one filter; the client loops if they want N.
- Push-notification / email integration on filter hits. SSE is the only delivery channel.
- Backfill on connect ("send me the last hour"). The stream is purely live; clients use `/events/recent` for the catch-up read.

---

## Tasks

Each task is **one commit**. Run `make check` + `make test` before stopping. Stop after each task; wait for the user before starting the next.

| # | Task | Files | Status |
|---|------|-------|--------|
| 1 | Alert Pydantic models — `AlertFilter` (input), `AlertFilterResponse`, `AlertEnvelope` + XOR (bbox vs center+radius) validator | `models/alerts.py`, `tests/unit/test_alerts_models.py` | ⬜ |
| 2 | `FilterMatcher` — pure match of an event against a filter (mag, bbox, center+radius via haversine) | `quake/alerts/matcher.py`, `tests/unit/test_filter_matcher.py` | ⬜ |
| 3 | `SubscriberRegistry` — async per-key fanout: subscribe / unsubscribe / publish | `quake/alerts/registry.py`, `tests/unit/test_subscriber_registry.py` | ⬜ |
| 4 | Postgres `pg_notify` trigger + `AlertListener` (lifespan-managed LISTEN task) | `database/migrations/*_events_notify.sql`, `quake/alerts/listener.py`, `quake/main.py`, `tests/unit/test_alert_listener.py` | ⬜ |
| 5 | `/alerts/filters` Manager + Views (CRUD, per-key scoping) | `quake/api/alerts/{main,views,models}.py`, `quake/main.py`, `tests/unit/test_alert_filters_api.py` | ⬜ |
| 6 | `/alerts/stream` SSE Manager + view; pin `sse-starlette` in `requirements.txt` | `quake/api/alerts/{main,views}.py`, `requirements.txt`, `tests/unit/test_alerts_stream_api.py` | ⬜ |
| 7 | `docs/alerts.md` — design note (LISTEN/NOTIFY hop, in-process matcher, filter semantics, single-pod limit) | `docs/alerts.md` | ⬜ |
| 8 | Integration smoke — end-to-end SSE | `tests/integration/test_alerts_stream.py` | ⬜ |

---

### Task 1 — Alert Pydantic models

**Scope.**

- New `models/alerts.py`:
  - `AlertFilter` — request DTO for POST/PATCH `/alerts/filters`. Fields: `min_magnitude` (float, optional, ≥0), `bbox_min_lat`/`bbox_min_lon`/`bbox_max_lat`/`bbox_max_lon` (floats, optional), `center_lat`/`center_lon`/`radius_km` (floats, optional, radius >0). `model_validator(mode="after")` enforces: at least one of (min_magnitude / bbox / center+radius) is set; the bbox group is all-or-nothing; the center+radius group is all-or-nothing; bbox XOR center+radius (cannot mix).
  - `AlertFilterResponse` — DB row shape (mirrors `AlertFilterRow`), `from_attributes=True`. Adds `id`, `api_key_id`, `created_at`, `updated_at` on top of the input fields.
  - `AlertEnvelope` — the SSE payload. Fields: `event_id`, `time`, `magnitude`, `magnitude_type`, `depth_km`, `latitude`, `longitude`, `place`, `url`. Pulled from `EventRow` (or the trigger JSON) at publish time.
- New `tests/unit/test_alerts_models.py`:
  - XOR validator: bbox-only OK, center+radius-only OK, both → `ValidationError`, partial bbox → error, partial center → error.
  - Empty filter (no fields) → `ValidationError`.
  - Negative `min_magnitude` / non-positive `radius_km` → `ValidationError`.
  - `AlertEnvelope` round-trips a sample event dict.

**Acceptance.**

- `make check` clean.
- `make test` passes.

**Commit message (proposed).**

```
feat(alerts): Pydantic models for filters + SSE envelope

AlertFilter (request DTO with bbox/center XOR validator),
AlertFilterResponse (DB row shape), AlertEnvelope (SSE payload).
No DB or API surface yet — models only, exercised by unit tests.
```

---

### Task 2 — `FilterMatcher`

**Scope.**

- New `quake/alerts/matcher.py`:
  - `matches(filter_row: AlertFilterRow, event: EventRow) -> bool` — pure function.
  - Composition: every set predicate must hold (AND within a single filter): `min_magnitude` if set, bbox if set, center+radius if set.
  - Haversine in km for the center+radius branch. Reuse the constants/formula from `EventsETL.query` if one already exists; otherwise inline a small private `_haversine_km` helper (no new deps).
  - Module-level docstring documents: AND-within-filter, NULL columns mean "predicate not set, skip".
- New `tests/unit/test_filter_matcher.py`:
  - Magnitude-only: pass / fail / equal-boundary.
  - Bbox-only: inside / outside / on-edge (inclusive boundary).
  - Center+radius: inside / outside / antimeridian-spanning case skipped (documented as "rectangle is in lat/lon space, treat as planar near equator" — V1 limitation).
  - Magnitude + bbox combined: passes both / fails one / fails both.
  - All-fields filter against a sample event.
  - Empty filter (no predicates set) → matches everything (documented — caller is expected to reject empty filters at the API layer via Task 1's validator).

**Acceptance.**

- `make check` clean.
- `make test` passes.

**Commit message (proposed).**

```
feat(alerts): FilterMatcher — match an event against a filter row

Pure function: AND across set predicates (mag / bbox / center+radius),
haversine in km for center+radius. NULL columns mean "predicate not
set, skip". Composition exercised by the unit-test matrix.
```

---

### Task 3 — `SubscriberRegistry`

**Scope.**

- New `quake/alerts/registry.py`:
  - `Subscriber` dataclass — `id: int`, `api_key_id: int`, `filters: list[AlertFilterRow]`, `queue: asyncio.Queue[AlertEnvelope]`.
  - `SubscriberRegistry` class:
    - `subscribe(api_key_id, filters) -> Subscriber` — assigns an id, allocates a bounded queue (default `maxsize=100`), stores under `_subs[id]`.
    - `unsubscribe(sub_id)` — pops the slot; idempotent on unknown id.
    - `publish(event)` — synchronously walk `_subs`, run `FilterMatcher.matches` against each subscriber's filters (OR across them — see design choice 3), and `queue.put_nowait` the envelope into each match. On `QueueFull`, drop the envelope for that slow subscriber and log a warning with the `(sub_id, api_key_id)` pair (back-pressure choice: live alerts beat dead alerts for everyone else).
    - `get_subscriber_count() -> int` — small accessor for observability / tests.
  - Module-level `_REGISTRY` singleton + `get_registry()` accessor; tests reset via a fixture that overwrites the singleton.
- New `tests/unit/test_subscriber_registry.py`:
  - `subscribe` returns distinct ids + an awaitable queue.
  - `publish` routes to matching subscribers (uses real `FilterMatcher`, real `AlertFilterRow`).
  - `publish` skips non-matching subscribers.
  - `publish` ORs across multiple filters for one subscriber.
  - `publish` on a full queue drops the envelope for that slot and keeps going.
  - `unsubscribe` removes the slot; subsequent publishes don't deliver to it.
  - Unknown `unsubscribe` is a no-op.
  - Empty registry: `publish` is a no-op (no error).

**Acceptance.**

- `make check` clean.
- `make test` passes.

**Commit message (proposed).**

```
feat(alerts): SubscriberRegistry — async per-key fanout bus

In-process pub/sub: each subscriber owns a bounded asyncio.Queue and
a snapshot of their filters. publish() runs FilterMatcher against
every active slot and routes matching envelopes; full queues drop
the envelope for that slot. Module-level singleton with reset hooks
for tests.
```

---

### Task 4 — Postgres `pg_notify` trigger + `AlertListener`

**Scope.**

- New migration `database/migrations/YYYYMMDDHHMMSS_events_notify.sql`:
  - `-- migrate:up`:
    - `CREATE OR REPLACE FUNCTION quake.events_notify() RETURNS trigger AS $$ ... $$ LANGUAGE plpgsql;` body calls `PERFORM pg_notify('quake_event_inserts', row_to_json(NEW)::text);` and `RETURN NEW;`.
    - `CREATE TRIGGER events_notify AFTER INSERT ON quake.events FOR EACH ROW EXECUTE FUNCTION quake.events_notify();` (use `DROP TRIGGER IF EXISTS … ; CREATE TRIGGER …` for idempotency on re-apply).
  - `-- migrate:down`: drop trigger then function.
- New `quake/alerts/listener.py`:
  - `AlertListener` class wrapping a long-lived async psycopg connection in autocommit + `LISTEN quake_event_inserts`.
  - Main loop: `async for notify in conn.notifies():` → `json.loads(notify.payload)` → construct `AlertEnvelope` via `model_validate` → `registry.publish(envelope)`.
  - Supervisor: outer `while not self._stop:` re-opens the connection and re-LISTENs if the loop exits, with exponential backoff (1s → 30s cap) logging each retry. Cancellation closes the connection and exits cleanly.
- `quake/main.py`:
  - Wrap the FastAPI app with a `lifespan` async context manager. On startup: spawn the listener via `asyncio.create_task(...)`. On shutdown: cancel the task and `await` its completion.
  - Keep the lifespan opt-in via a class flag (default on) so the SSE-less test fixtures don't fight the live listener.
- New `tests/unit/test_alert_listener.py` (runs against the sandbox DB via the existing unit conftest):
  - **Trigger fires.** INSERT a row into `quake.events` via `EventsETL.upsert_many`; assert the listener's registry receives an envelope with the right `event_id` (assert via `asyncio.wait_for(queue.get(), timeout=5.0)` against a registry-subscribed queue).
  - **Malformed payload tolerated.** Manually call `SELECT pg_notify('quake_event_inserts', 'not json')` and assert the listener logs + keeps running (next valid INSERT still delivers).
  - **Multiple inserts in one transaction.** `upsert_many([...])` fires one NOTIFY per row; assert the registry queue collects all of them.

**Acceptance.**

- `make check` clean.
- `make test` passes.
- `make migrate-test` (sandbox forward/down/forward cycle) is clean.

**Commit message (proposed).**

```
feat(alerts): pg_notify trigger on quake.events INSERT + AlertListener

New migration installs an AFTER INSERT trigger that calls
pg_notify('quake_event_inserts', row_to_json(NEW)). AlertListener
owns an async psycopg LISTEN connection started in the FastAPI
lifespan; decoded envelopes go to the SubscriberRegistry. Auto-
reconnects with exponential backoff on connection loss.
```

---

### Task 5 — `/alerts/filters` Manager + Views

**Scope.**

- New `quake/api/alerts/main.py`:
  - `AlertFiltersManager` with `APIRouter(prefix="/alerts/filters", dependencies=[Depends(Authenticate())])` (any valid key).
- New `quake/api/alerts/views.py`:
  - `AlertFiltersManagerViews` with `list`, `create`, `update`, `delete`.
  - `list` — `AlertFiltersETL().for_api_key(row.id)` → `AlertFiltersListResponse(count, filters)`.
  - `create` — POST body `AlertFilter` (Task 1's DTO) → `AlertFiltersETL().insert(api_key_id=row.id, **body.model_dump())` → 201 with the new `AlertFilterResponse`.
  - `update` — PATCH `/{filter_id}` body `AlertFilter` → full-replacement update via `AlertFiltersETL().update(filter_id, row.id, **body.model_dump())`; `False` return → 404 (`detail="no such filter"`). 200 with refreshed response.
  - `delete` — `AlertFiltersETL().delete(filter_id, row.id)`; `False` → 404; 204 on success.
  - Every view receives the `ApiKeyRow` by adding `current_key: ApiKeyRow = Depends(Authenticate())` on the view signature (one extra dep call per request — FastAPI dedupes; same pattern would work for future per-key endpoints).
- New `quake/api/alerts/models.py`:
  - `AlertFiltersListResponse(count, filters)`. Re-exports `AlertFilter` / `AlertFilterResponse` from `models/alerts.py` for the OpenAPI schema cohesion.
- `quake/main.py` — mount `AlertFiltersManager`.
- New `tests/unit/test_alert_filters_api.py`:
  - Two clients via the same StubVault fixture pattern from Epic 5 tests: `client_a` (key A) and `client_b` (key B).
  - **List empty** — GET returns `{"count": 0, "filters": []}`.
  - **Create round-trip** — POST a magnitude+bbox filter; assert 201 + ETL row exists scoped to key A's id.
  - **List shows created filters** in order.
  - **Update** a filter; assert fields changed.
  - **Update foreign filter is 404** — key B tries to update key A's filter id; ETL's `api_key_id` WHERE catches it; view 404s.
  - **Delete** — 204; subsequent GET drops it.
  - **Delete foreign filter is 404** — analogous cross-key defence.
  - **Invalid filter body** (bbox + center together) → 422.
  - **No auth** → 401.

**Acceptance.**

- `make check` clean.
- `make test` passes.

**Commit message (proposed).**

```
feat(api): /alerts/filters (per-key CRUD)

GET lists this key's filters; POST creates one; PATCH/{id} replaces;
DELETE/{id} removes. Every write is scoped to the authenticated key
via the ETL's api_key_id WHERE clause. Bbox XOR center+radius is
enforced application-side via the AlertFilter validator from Task 1.
```

---

### Task 6 — `/alerts/stream` SSE

**Scope.**

- `requirements.txt` — uncomment + pin `sse-starlette` (latest 2.x compatible with Python 3.14 + FastAPI 0.136).
- `quake/api/alerts/main.py` — add a second router `AlertsStreamManager` with `APIRouter(prefix="/alerts", dependencies=[Depends(Authenticate())])`.
- `quake/api/alerts/views.py` — `AlertsStreamManagerViews.stream(request, current_key)`:
  - Load `AlertFiltersETL().for_api_key(current_key.id)`.
  - If empty, raise `HTTPException(400, "no filters configured — POST one to /alerts/filters first")` so the client doesn't open a stream that can never deliver anything.
  - `subscriber = registry.subscribe(current_key.id, filters)`.
  - Inner async generator: loop reading from `subscriber.queue`, yield `{"event": "alert", "data": envelope.model_dump_json()}`. Bail on `await request.is_disconnected()` periodically (sse-starlette wraps this).
  - `finally: registry.unsubscribe(subscriber.id)`.
  - Return `EventSourceResponse(generator, send_timeout=15.0, ping=15)`.
- `quake/main.py` — mount `AlertsStreamManager`.
- New `tests/unit/test_alerts_stream_api.py`:
  - Subscribe via `TestClient.stream("GET", "/alerts/stream", headers=…)` and read N events.
  - **Publish round-trip** — seed a filter, open the stream, push one envelope via `registry.publish` directly, assert the client reads `event: alert\ndata: {…}`.
  - **Filter mismatch is dropped** — second publish with a non-matching envelope is not delivered.
  - **No filters → 400** before the stream opens.
  - **No auth → 401**.
  - **Disconnect cleans up** — close the stream, allow one event loop tick, assert `registry.get_subscriber_count()` is back to its pre-test value.

**Acceptance.**

- `make check` clean.
- `make test` passes.

**Commit message (proposed).**

```
feat(api): /alerts/stream — per-key SSE of matching events

EventSourceResponse with a generator backed by SubscriberRegistry.
On connect: snapshot this key's filters, subscribe. Each new event
matched against the snapshot is emitted as `event: alert` with the
AlertEnvelope JSON. Disconnect cleanly unsubscribes the slot.
Mid-stream filter edits require a reconnect to take effect.
```

---

### Task 7 — `docs/alerts.md`

**Scope.**

- New `docs/alerts.md`:
  - Block diagram (ASCII): Celery worker → `quake.events INSERT` → trigger → `pg_notify` → `AlertListener` → `SubscriberRegistry` → `FilterMatcher` → connected SSE clients.
  - **Why LISTEN/NOTIFY?** Section on the worker/API process boundary and why Postgres is the cheapest cross-process channel here.
  - **Filter semantics.** OR across a key's filters; AND within one filter (mag + bbox|center). Snapshot at connect time → reconnect to refresh.
  - **Single-pod limit.** Explicit. Notes the migration path if/when it changes (move publish behind RabbitMQ fanout exchange; matcher stays in-process per pod).
  - **Operator notes.** How to inspect live subscribers (`SubscriberRegistry.get_subscriber_count`); how to confirm the trigger is installed (`\df+ quake.events_notify` in psql); curl recipe for a manual SSE test.

**Acceptance.**

- `make check` clean.
- `make test` passes (no test changes; the doc adds zero code).

**Commit message (proposed).**

```
docs(alerts): SSE pipeline design note

LISTEN/NOTIFY transport, in-process matcher + fanout, filter
semantics (OR-across / AND-within / connect-time snapshot),
single-pod limit, operator inspection tips.
```

---

### Task 8 — Integration smoke — end-to-end SSE

**Scope.**

- New `tests/integration/test_alerts_stream.py`:
  - Per-test fixture truncates `quake.events`, `quake.alert_filters`, `quake.api_keys`, `quake.event_revisions`, `quake.ingestion_runs`; ensures `INGESTION_LOCK` is cleared.
  - Issue an authenticated key, POST one filter (mag ≥ 4.0).
  - Open the SSE stream via `httpx.AsyncClient.stream` against the live `Quake` app (lifespan-enabled, real listener task running).
  - In a sibling task, INSERT one matching event into `quake.events` via `EventsETL().upsert_many([_event_mag_5_0])`. This fires the real trigger → real NOTIFY → real listener → real registry → live SSE client.
  - Assert the client receives the `event: alert` line + the envelope's `event_id` matches what we inserted, within a 5s timeout.
  - Also INSERT one non-matching event (mag 1.0) and assert no further event arrives in a 1s wait window before closing.

**Acceptance.**

- `make check` clean.
- `make test` passes (integration suite runs as part of `make test`).

**Commit message (proposed).**

```
test(integration): end-to-end SSE alerts smoke

Authenticates, posts a mag-≥-4.0 filter, opens /alerts/stream,
inserts one matching and one non-matching event directly into
quake.events. The trigger → NOTIFY → AlertListener → registry →
SSE client path delivers the matching envelope and drops the
non-matching one.
```

---

## After all tasks ship

- User confirms commit range, then asks Claude to:
  - Mark Epic 6 ✅ Done in `MASTER_PLAN.md` with the commit range.
  - Optionally archive this `PLAN.md` to `docs/history/epic-06-sse-alerts.md`.
- Root `PLAN.md` slot is then free for Epic 7 (Frontend).
