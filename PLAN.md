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
| 1 | Alert Pydantic models — `AlertFilter` (input), `AlertFilterResponse`, `AlertEnvelope` + XOR (bbox vs center+radius) validator | `models/alerts.py`, `tests/unit/test_alerts_models.py` | ✅ |
| 2 | `FilterMatcher` — pure match of an event against a filter (mag, bbox, center+radius via haversine) | `quake/alerts/matcher.py`, `tests/unit/test_filter_matcher.py` | ✅ |
| 3 | `SubscriberRegistry` — async per-key fanout: subscribe / unsubscribe / publish | `quake/alerts/registry.py`, `tests/unit/test_subscriber_registry.py` | ✅ |
| 4 | Postgres `pg_notify` trigger + `AlertListener` (lifespan-managed LISTEN task) | `database/migrations/*_events_notify.sql`, `quake/alerts/listener.py`, `quake/main.py`, `tests/unit/test_alert_listener.py` | ✅ |
| 5 | `/alerts/filters` Manager + Views (CRUD, per-key scoping) | `quake/api/alerts/{main,views,models}.py`, `quake/main.py`, `tests/unit/test_alert_filters_api.py` | ✅ |
| 6 | `/alerts/stream` SSE Manager + view; pin `sse-starlette` in `requirements.txt` | `quake/api/alerts/{main,views}.py`, `requirements.txt`, `tests/unit/test_alerts_stream_api.py` | ⬜ |
| 7 | `docs/alerts.md` — design note (LISTEN/NOTIFY hop, in-process matcher, filter semantics, single-pod limit) | `docs/alerts.md` | ⬜ |
| 8 | Integration smoke — end-to-end SSE | `tests/integration/test_alerts_stream.py` | ⬜ |

---

### Task 1 — Alert Pydantic models ✅

**Outcome.**

Shipped as planned with two minor scope additions, both pure tests on planned production code. Changes:

- `models/alerts.py` (new) — three Pydantic models:
  - `AlertFilter` — request DTO. Per-field range constraints via `Field(ge=…, le=…, gt=…)` cover the magnitude floor (`-1.0 ≤ min_magnitude ≤ 10.0`), bbox lat/lon ranges, center lat/lon ranges, and `radius_km > 0`. The `model_validator(mode="after")` enforces the four shape rules: partial bbox rejected, partial center+radius rejected, both shapes set at once rejected, fully-empty filter rejected. Adds a bbox-ordering check (`bbox_min_lat ≤ bbox_max_lat`, `bbox_min_lon ≤ bbox_max_lon`) once all four bbox fields are present. `extra="forbid"` rejects rogue keys.
  - `AlertFilterResponse` — DB-row response with `from_attributes=True` so it consumes `AlertFilterRow` directly. Carries `id` / `api_key_id` / `created_at` / `updated_at` on top of the input fields.
  - `AlertEnvelope` — SSE payload. Slim projection of `EventRow` (`event_id`, `time`, `magnitude`, `magnitude_type`, `depth_km`, `latitude`, `longitude`, `place`, `url`). Default `extra="ignore"` (no `forbid`) so the listener can feed it a `row_to_json(NEW)` dict with extra columns (`inserted_at`, `tsunami`, `status`) without crashing.
- `tests/unit/test_alerts_models.py` (new) — 21 tests across three sections: happy-path constructions, shape errors, per-field range errors, plus the DB-row → response round-trip and the row-shaped-dict → envelope round-trip.

**Deviations / additions beyond the spec.**

1. **Two extra tests** beyond the plan's matrix:
   - `test_filter_inverted_bbox_lat_is_rejected` / `test_filter_inverted_bbox_lon_is_rejected` — exercise the bbox-ordering branch that was added to the validator (mismatched min/max would otherwise create a non-empty rectangle that always evaluates false, an easy operator footgun).
   - `test_filter_unknown_field_is_rejected` — coverage for the `extra="forbid"` config.
2. **`AlertEnvelope` deliberately does NOT set `extra="forbid"`.** Documented inline. The pg_notify path will feed it `row_to_json(NEW)` which includes columns we don't want on the wire (`inserted_at`, `updated_at`, `tsunami`, `status`) but also don't want to reject. The test `test_envelope_consumes_row_shaped_dict` locks this in.

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 138 unit tests (21 new under `test_alerts_models.py`) + 3 integration.

**Commit message (proposed).**

```
feat(alerts): Pydantic models for filters + SSE envelope

models/alerts.py: AlertFilter (request DTO with bbox-XOR-center+radius
validator, magnitude / lat / lon / radius range checks, bbox ordering,
extra=forbid), AlertFilterResponse (DB-row response, from_attributes),
AlertEnvelope (slim SSE projection of EventRow, tolerates row_to_json
dicts).

No API or DB surface in this commit — Tasks 2-6 consume these models.
21 unit tests cover the happy paths, every shape error, and the
EventRow / row_to_json round-trip into AlertEnvelope.
```

---

### Task 2 — `FilterMatcher` ✅

**Outcome.**

Shipped as planned with three additive test expansions (no production-code drift). Changes:

- `quake/alerts/matcher.py` (new) — pure `matches(filter_row, event) -> bool` over the three predicates (`min_magnitude` / bbox / center+radius). Each predicate is **set** when its DB columns are non-NULL; unset predicates are skipped (`return True` for that branch). Combination is AND-within-a-filter. The haversine in `database/etls/events.py:187` is inline SQL and not reusable from Python — added a small private `_haversine_km(lat1, lon1, lat2, lon2) -> float` using `math.radians` / `math.asin` and `_EARTH_RADIUS_KM = 6371.0`.
- `tests/unit/test_filter_matcher.py` (new) — 23 tests across the predicate matrix + combinations.

**Implementation note worth recording.**

`_bbox_bounds(f) -> tuple[float, float, float, float] | None` and `_center_bounds(f) -> tuple[float, float, float] | None` return narrowed tuples instead of bare booleans because pyright/mypy can't see across an `is_set` boolean check that ``f.bbox_min_lat`` is non-None when later used in a comparison. The four extra lines of indirection avoid the `# type: ignore` / `assert` patterns that the static-analysis gate forbids. Documented inline by the function signatures.

**Deviations / additions beyond the spec.**

1. **Bbox-edge coverage via `@pytest.mark.parametrize`.** Plan listed one "on-edge" case; expanded to all four edges plus both diagonals. The bbox-inclusive contract is what later filter changes are most likely to break.
2. **`test_center_radius_just_outside_fails`** — exercises the "exactly outside the radius" branch separately from "way outside". The haversine boundary is more bug-prone than the inside/outside happy paths.
3. **`test_all_predicates_set_*`** — locks in matcher behavior when an `AlertFilterRow` has bbox AND center+radius set simultaneously. The API validator rejects that combination at the boundary, but the DB row model is accommodating, so the matcher's AND semantics must hold for hand-constructed rows (seeded test data, future migration scenarios).

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 161 unit tests (23 new under `test_filter_matcher.py`) + 3 integration.

**Commit message (proposed).**

```
feat(alerts): FilterMatcher — match an event against a filter row

Pure function: AND across set predicates (mag / bbox / center+radius),
haversine in km for center+radius. NULL columns mean "predicate not
set, skip". The DB row's mutually-exclusive shape (bbox vs center+
radius) is enforced at the API layer; the matcher itself treats them
as independent predicates that compose with AND if both happen to be
set. Composition exercised by 23 unit tests.
```

---

### Task 3 — `SubscriberRegistry` ✅

**Outcome.**

Shipped as planned with one signature choice worth recording and four additive tests. Changes:

- `quake/alerts/registry.py` (new):
  - `Subscriber` — `@dataclass` with `id`, `api_key_id`, `filters: list[AlertFilterRow]`, `queue: asyncio.Queue[AlertEnvelope]` (the queue's `field(repr=False)` keeps log lines readable).
  - `SubscriberRegistry`:
    - `subscribe(api_key_id, filters) -> Subscriber` — `itertools.count` for ids, bounded queue via `asyncio.Queue(maxsize=…)`, default `maxsize=100`, override via constructor arg for tests.
    - `unsubscribe(sub_id)` — `dict.pop(…, None)`, logs only when a slot was actually removed.
    - `publish(event: EventRow)` — iterates `_subs.values()`, skips empty filter lists, runs `any(matches(f, event) for f in sub.filters)` for the OR-across semantics, lazily constructs the `AlertEnvelope` once on the first match, `put_nowait` into each match. `asyncio.QueueFull` catches and warns with `(sub_id, api_key_id, event_id)`.
    - `get_subscriber_count()` for tests + observability.
  - Module-level `_REGISTRY: SubscriberRegistry | None`, `get_registry()` lazy init, plus `reset_registry_for_tests()` exposed alongside (the test hook ships in the production module so tests don't need to reach into a `_REGISTRY` private name).
- `tests/unit/test_subscriber_registry.py` (new) — 14 async tests covering lifecycle, routing, OR semantics, back-pressure (a `maxsize=1` registry with a slot pre-filled by hand → publish drops for that slot but delivers to a fast neighbour), and the singleton accessor.

**Implementation notes worth recording.**

1. **`publish(event: EventRow)` — not `publish(envelope)`.** Takes the `EventRow` so the matcher (Task 2) receives its declared input type with no cast or `# type: ignore`. The registry builds `AlertEnvelope.model_validate(event)` **lazily** — zero allocation if nothing matches.
2. **Empty filter list short-circuits before the matcher.** A subscriber with `filters=[]` is unreachable by `publish` even though Task 2's matcher would route every event to an empty filter ("vacuously true"). Defence-in-depth against an empty-filters subscription accidentally subscribing to the firehose; the API layer (Task 6) will reject `subscribe` with no filters too, but this layer doesn't trust callers either.
3. **Singleton + test hook live in the production module.** Alternative was a `tests/_alerts.py` helper reaching into `_REGISTRY`. Keeping `reset_registry_for_tests()` next to the singleton means callers don't need to know the private name, and pyright sees the symbol.

**Deviations / additions beyond the spec.**

1. **Four extra tests** beyond the plan's matrix:
   - `test_publish_delivers_exactly_once_when_multiple_filters_all_match` — locks in the `any(...)` short-circuit (two filters both match → queue holds exactly one envelope, not two).
   - `test_publish_skips_subscriber_with_empty_filter_list` — covers the empty-filter-list guard described above.
   - `test_publish_routes_to_multiple_matching_subscribers` — multi-subscriber fanout invariant.
   - `test_get_registry_returns_same_instance` / `test_reset_registry_for_tests_rebuilds_the_singleton` — locks in the singleton + test-hook contract.

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 175 unit tests (14 new under `test_subscriber_registry.py`) + 3 integration.

**Commit message (proposed).**

```
feat(alerts): SubscriberRegistry — async per-key fanout bus

In-process pub/sub. Each Subscriber owns a bounded asyncio.Queue
(maxsize=100) and a snapshot of their filters taken at subscribe
time. publish(EventRow) walks every slot, ORs across the snapshot
via FilterMatcher, and put_nowait's an AlertEnvelope into matching
queues. Full queues drop the envelope for that slot and log; live
alerts beat dead alerts.

Module-level singleton with a reset hook so tests don't fight
production state. Empty filter lists short-circuit before the
matcher to keep the empty-snapshot path away from the firehose.
```

---

### Task 4 — Postgres `pg_notify` trigger + `AlertListener` ✅

**Outcome.**

Shipped as planned with three small implementation refinements (documented below) and one extra defensive test. Changes:

- `database/migrations/20260519154655_events_notify.sql` (new) — `quake.events_notify()` plpgsql trigger function that `PERFORM pg_notify('quake_event_inserts', row_to_json(NEW)::text);` and returns NEW. `events_notify_trigger AFTER INSERT ON quake.events FOR EACH ROW` wires it up; the up migration uses `DROP TRIGGER IF EXISTS … ; CREATE TRIGGER …` for idempotent re-runs. Down drops trigger + function.
- `quake/alerts/listener.py` (new):
  - `AlertListener(registry)` constructor takes the in-process registry by reference (injection makes tests trivially hermetic).
  - `run()` — supervisor: `while not self._stop.is_set()` opens a fresh connection via `psycopg.AsyncConnection.connect(..., autocommit=True)`, issues `LISTEN quake_event_inserts`, sets the `ready` event, and enters a `while not stop: async for notify in conn.notifies(timeout=1.0): ...` inner loop. Exceptions trigger exponential backoff (1.0s → 30.0s cap) via `asyncio.wait_for(self._stop.wait(), timeout=backoff)` — that double-purpose call also makes a `stop()` during backoff exit immediately. `CancelledError` short-circuits to a clean exit.
  - `stop()` — sets the stop event; safe to call from any context (sync from a lifespan handler is fine).
  - `ready: asyncio.Event` — set after the LISTEN command succeeds. Tests `await listener.ready.wait()` before issuing INSERTs to avoid the LISTEN-vs-INSERT race.
  - `_handle_notify(payload)` — `json.loads` then `EventRow.model_validate`; either raise is logged + swallowed (a bad payload must not take down the supervisor). On success, calls `self._registry.publish(event)`.
  - `_build_conninfo()` — pulls `host/port/user/password/dbname` from the same `get_environmental_variables().database` block the pool already uses.
- `quake/main.py` — wraps the FastAPI app with an `_lifespan` `asynccontextmanager` that does `listener = AlertListener(get_registry()); task = asyncio.create_task(listener.run())` on entry; on exit calls `listener.stop()` and `asyncio.wait_for(task, timeout=10.0)`, falling back to `task.cancel()` + `await` if the listener exceeds the budget.
- `tests/unit/test_alert_listener.py` (new) — 4 async tests against the sandbox DB. A `pytest_asyncio.fixture` builds a fresh `SubscriberRegistry`, subscribes a wide filter, starts the listener, awaits `ready.wait()`, hands over to the test, and tears down via `stop()` + bounded `await`.

**Three implementation refinements worth recording.**

1. **`notifies(timeout=1.0)` instead of a bare `async for`.** With no timeout, the iterator hangs on a dormant channel until the *next* NOTIFY ever arrives — meaning `stop()` is invisible until something triggers a notification. A 1-second timeout makes the inner loop return periodically so the outer `while not stop` can exit. Cut listener-test runtime from ~24s to ~8s. Documented in the `_listen_once` docstring.
2. **`AlertListener.ready` property.** Not in the plan. Tests need a synchronisation point between "listener has issued LISTEN" and "test issues INSERT" — without it, ~5% of test runs raced the LISTEN setup and lost the first notification. The event is set inside `_listen_once` after `LISTEN` succeeds; production never awaits it, so zero behavioural impact in normal use. Lives next to `_stop` for symmetry.
3. **Lifespan + zero test touches.** Starlette `TestClient` only fires lifespan inside `with TestClient(app) as c:`. All 9 existing test sites build a plain `TestClient(quake.app)`, so the listener stays off in those — no fixture updates required. Task 8 opt-in is explicit (`with TestClient(...)` or `httpx.AsyncClient` with manual lifespan). The plan called for a class flag (`enable_alert_listener`); the TestClient behaviour makes the flag unnecessary. Documented in the new `Quake._lifespan` docstring.

**Other deviation.**

4. **One extra test:** `test_json_with_wrong_shape_is_skipped_and_next_event_still_delivers` — valid JSON whose shape isn't an `EventRow`. Symmetric with `test_malformed_payload_is_skipped_…` (which covers non-JSON garbage); together they lock both branches of `_handle_notify`'s defensive parse.

**Verification.** `make migrate-test` clean (sandbox forward → down → forward cycle). `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 179 unit tests (4 new under `test_alert_listener.py`) + 3 integration.

**Commit message (proposed).**

```
feat(alerts): pg_notify trigger on quake.events INSERT + AlertListener

New migration installs an AFTER INSERT FOR EACH ROW trigger that
PERFORMs pg_notify('quake_event_inserts', row_to_json(NEW)). The
new AlertListener owns an async psycopg LISTEN connection started
in the FastAPI lifespan; decoded payloads land in the singleton
SubscriberRegistry via publish(EventRow). Auto-reconnects with
exponential backoff (1s → 30s) on connection loss; clean shutdown
via stop() + a 1s polling notifies(timeout) so a dormant channel
doesn't stall cancellation.

Existing TestClient-based tests don't enter the app's lifespan
context manager, so the listener stays off for those — no test
fixtures need updating. The Task 8 integration smoke will opt in.
```

---

### Task 5 — `/alerts/filters` Manager + Views ✅

**Outcome.**

Shipped as planned with one auth-wiring deviation (kept the security posture, dropped the duplicated work) and a small ETL addition. Changes:

- `database/etls/alert_filters.py` — added `get_by_id(filter_id, api_key_id) -> AlertFilterRow | None`. The existing `insert` returns only the new id and `update` returns only a `bool`; the create/update views need the full row (with DB-assigned `created_at` / `updated_at`) for their `AlertFilterResponse` body. The new method keys on both `id` and `api_key_id` so it inherits the same cross-key defence as the other methods.
- `quake/api/alerts/models.py` (new) — re-exports `AlertFilter` and `AlertFilterResponse` from `models/alerts.py` for OpenAPI-import cohesion; defines `AlertFiltersListResponse(count, filters)`.
- `quake/api/alerts/views.py` (new) — `AlertFiltersManagerViews` with `list_filters` / `create_filter` / `update_filter` / `delete_filter`. Every view takes `current_key: ApiKeyRow = Depends(Authenticate())` and threads `current_key.id` into the ETL. Create + update read back the row via `get_by_id` for the response; if the read-back returns `None` (race with a concurrent delete from the same key), the view 500s with a clear message rather than leaking a confusing 404 or empty body.
- `quake/api/alerts/main.py` (new) — `AlertFiltersManager` mounting `APIRouter(prefix="/alerts/filters")`. Routes: GET (200), POST (201 via `status_code=…`), PATCH `/{filter_id}` (200), DELETE `/{filter_id}` (204). All under `tags=["Alerts"]` with explicit `operation_id`s (`alerts_filters_list` / `_create` / `_update` / `_delete`).
- `quake/main.py` — mounts `AlertFiltersManager` after `IngestManager`.
- `tests/unit/test_alert_filters_api.py` (new) — 15 tests across two clients (`client_a`, `client_b`) sharing one `StubVault`, plus a no-auth client. Covers: empty list, per-key list isolation, create round-trip + ETL cross-check, empty-filter 422, bbox+center 422, update happy path, update unknown 404, update foreign 404 (with row-not-mutated defence-in-depth check), delete 204 + ETL cross-check, delete unknown 404, delete foreign 404 (with row-still-present check), and 401 on every verb without auth.

**Auth-wiring deviation (kept security posture, dropped duplicated work).**

The plan declared auth at both the **router level** (``APIRouter(dependencies=[Depends(Authenticate())])``) and the **view signature level** (``current_key: ApiKeyRow = Depends(Authenticate())``), arguing "one extra dep call per request — FastAPI dedupes". On inspection, FastAPI's dependency cache keys on the callable's identity, and ``Authenticate()`` constructs a fresh class instance at each callsite — two ``Authenticate()`` calls are distinct callables, so they don't dedupe. The router-level dep would have doubled the DB+Vault round-trip per request without adding any guarantee the view-level dep doesn't already provide. Shipping resolution: **view-signature dep only**. Same security coverage, half the auth work. Documented in `quake/api/alerts/main.py`'s docstring.

**Other deviations / additions.**

1. **`AlertFiltersETL.get_by_id`** — not in the original scope but required by the views' "return the full row" contract. The alternative (re-querying via `for_api_key` then filtering by id in Python) would have made every create/update an O(N) read for the just-written row. The targeted SELECT is cheaper and matches the existing `ApiKeysETL.get_by_id` pattern from Epic 5.
2. **Three extra tests** beyond the planned 9:
   - `test_list_returns_only_this_keys_filters` — explicit cross-key list isolation (key A's GET never returns key B's rows). Symmetric to the per-key-scoped update/delete defence tests.
   - `test_create_rejects_empty_filter` — pins the AlertFilter validator behaviour at the API boundary. Mirrors Task 1's `test_filter_empty_payload_is_rejected` at the unit layer.
   - `test_update_foreign_filter_is_404` asserts the row was **not** mutated after the 404 — defence-in-depth check that the ETL's WHERE actually scoped the UPDATE rather than relying solely on the post-check return.
3. **Read-back-after-write 500 paths.** Create and update both call `get_by_id` after the write. A `None` return there could only happen if a concurrent delete from the same key landed between the INSERT/UPDATE and the SELECT — a real race, just an unlikely one. The view raises `HTTPException(500, detail="filter inserted/updated but not found on read-back")` so the client sees an honest "retry" signal rather than a misleading 404. No production change; documented inline because the alternative paths weren't obvious from the spec.

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 194 unit tests (15 new under `test_alert_filters_api.py`) + 3 integration.

**Commit message (proposed).**

```
feat(api): /alerts/filters (per-key CRUD)

AlertFiltersManager + Views serve GET (list), POST (create, 201),
PATCH /{id} (update, 200), DELETE /{id} (delete, 204). Each view
takes Depends(Authenticate()) and threads ApiKeyRow.id into the
ETL — the existing api_key_id WHERE in update/delete is the cross-
key defence, and a new AlertFiltersETL.get_by_id (also api_key_id-
scoped) backs the response shape on create/update.

Auth declared at the view signature, not the router — FastAPI
doesn't dedupe per-call Authenticate() instances, so a router-
level dep would double the DB+Vault round-trip per request.

15 unit tests across two clients pin the contract: list/create/
update/delete round-trips, empty-filter and bbox+center rejections,
cross-key updates and deletes returning 404 without mutating the
foreign row, and 401 on every verb without auth.
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
