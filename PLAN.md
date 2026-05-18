# PLAN.md — Epic 5: API-key auth + admin surface

**Status:** 🟡 In progress
**Epic source:** [`MASTER_PLAN.md`](MASTER_PLAN.md) — Epic 5
**Branch:** new feature branch off `kantarelis` (PRs target `kantarelis`)

---

## Goal

Introduce an API-key auth layer and the first admin endpoints:

- `Authenticate` FastAPI dependency that validates `Authorization: Bearer <key>` against the `quake.api_keys` registry, cross-checks the raw key against Vault, refuses revoked keys, and enforces a `required_scope` argument when supplied.
- Two issuance scripts surfaced as `make issue-api-key` and `make revoke-api-key`. Issuance generates a random key, writes the hash to the DB, stores the raw key in Vault, and prints the raw key once.
- Retrofit Epic-4 `/events*` routes to require **any** valid key (no scope).
- New admin endpoints (all require an `admin`-scoped key):
  - `GET /admin/locks` — list all `endpoint_locks`.
  - `POST /admin/locks/{lock_name}` — set / update a lock (with `reason`, `locked_by`).
  - `DELETE /admin/locks/{lock_name}` — clear a lock.
  - `POST /admin/ingest/trigger` — enqueue `poll_usgs` and return `{task_id, queued_at}`.
  - `GET /admin/ingest/status` — return the latest N `ingestion_runs`.
- Wire `INGESTION_LOCK` into `poll_usgs`: when the lock is set, the task records the skip and returns without hitting USGS.
- `docs/vault.md` — Vault path layout for API keys + lifecycle notes.

## Design choices (locked up-front so tasks don't re-litigate)

1. **Two-tier auth model.**
   - **Public** (no key): `/health`, `/metrics`, `/env`. Ops + Prometheus stay unauthenticated.
   - **Authenticated** (any valid key): `/events`, `/events/recent`. Future SSE routes from Epic 6 default to the same tier.
   - **Admin scope** (`"admin"` in `api_keys.scopes`): every `/admin/*` route.
2. **Vault layout.** One KV path per key — `secret/api-keys/<key_id>`, payload `{raw_key, label, issued_at}`. `Authenticate` resolves hash → DB row → `key_id` → Vault path → compare raw. Issue/revoke each touch a single path; no concurrent-write race.
3. **Trigger semantics.** `POST /admin/ingest/trigger` enqueues `poll_usgs.delay()` and returns `{task_id, queued_at}` immediately. `/admin/ingest/status` reads `ingestion_runs` for the actual outcome. Matches how Beat invokes the task — no second code path.
4. **Lock enforcement.** `poll_usgs` checks `INGESTION_LOCK` at the top of the task. When locked, it writes an `ingestion_runs` row with `error="INGESTION_LOCK active"`, `inserted_count=0`, `updated_count=0`, `revision_count=0`, finalises `finished_at`, and returns. This avoids a schema migration (no new `status` column) while keeping the skip visible in observability.
5. **Key format.** `qkf_` prefix + 32 hex chars (16 random bytes via `secrets.token_hex(16)`). Prefix makes leaked keys greppable; the entropy is well above brute-force range so plain SHA-256 (no salt) is the hash.
6. **`Authenticate` shape.** Class-based dependency with `__init__(*, required_scope: str | None = None)`. Usage: `Depends(Authenticate())` for any-key routes, `Depends(Authenticate(required_scope="admin"))` for admin routes. Returns the `ApiKeyRow` so views can log/audit if needed. Uses `HTTPBearer(auto_error=False)` so we own the 401 envelope.
7. **Failure codes.** Missing/malformed header → 401 with `{"detail": "missing or malformed Authorization header"}`. Unknown / revoked key → 401 `"invalid api key"`. Valid key but missing scope → 403 `"missing required scope: <scope>"`. Bandit-safe: no key material in error messages or logs.
8. **Test pattern.** A shared helper `tests/_auth.py` issues a key (any / admin) directly against the sandbox DB + a Vault stub, returning `(raw_key, headers)`. Unit tests use it via a fixture; no live Vault container needed for the test suite (the stub speaks the same minimal interface).

## Out of scope

- User accounts / signup / login / email flows (intentionally absent — see decision log entry "Auth model: API-key only").
- Per-key rate limiting / quotas.
- Per-key data scoping (every authed key sees the same earthquake data).
- OAuth, OIDC, JWT — no third-party identity in this repo.
- `/admin/keys` CRUD via HTTP. Keys are minted with `make issue-api-key` only.
- Alert filters (Epic 6).
- HTTP-level metrics for auth outcomes (Epic 8).

---

## Tasks

Each task is **one commit**. Run `make check` + `make test` before stopping. Stop after each task; wait for the user before starting the next.

| # | Task | Files | Status |
|---|------|-------|--------|
| 1 | Auth primitives — `Authenticate` dep + key hashing + Vault key layout + `docs/vault.md` | `quake/api/auth.py`, `docs/vault.md`, `tests/unit/test_auth.py`, `tests/_auth.py`, `makefile` | ✅ |
| 2 | `make issue-api-key` + `make revoke-api-key` + scripts + unit tests | `scripts/{issue,revoke}_api_key.py`, `makefile`, `tests/unit/test_api_key_scripts.py`, `database/etls/api_keys.py`, `functions/vault.py`, `tests/_auth.py` | ✅ |
| 3 | Retrofit `/events*` with `Authenticate()` (no scope) | `quake/api/events/main.py`, `tests/unit/test_events_api_recent.py`, `tests/unit/test_events_api_query.py`, `tests/unit/test_main_api.py`, `tests/integration/test_read_api.py` | ✅ |
| 4 | `EndpointLocksETL` + `poll_usgs` gating on `INGESTION_LOCK` | `database/etls/endpoint_locks.py`, `database/etls/ingestion_runs.py`, `quake/events/ingest.py`, `tests/unit/test_endpoint_locks_etl.py`, `tests/unit/test_ingest.py` | ✅ |
| 5 | `/admin/locks` Manager + Views (admin-scoped) | `quake/api/locks/{main,views,models}.py`, `quake/main.py`, `tests/unit/test_locks_api.py` | ⬜ |
| 6 | `/admin/ingest/*` Manager + Views (admin-scoped, async trigger) | `quake/api/ingest/{main,views,models}.py`, `quake/main.py`, `tests/unit/test_ingest_api.py` | ⬜ |
| 7 | Integration smoke — end-to-end auth + admin surface | `tests/integration/test_auth_admin.py` | ⬜ |

---

### Task 1 — Auth primitives + `docs/vault.md` ✅

**Outcome.**

Shipped as planned with two refinements (documented below). Changes:

- `quake/api/auth.py` (new): `hash_key` (SHA-256 hex), `generate_raw_key` (`qkf_<hex32>` via `secrets.token_hex(16)`), `vault_path(key_id)` → `api-keys/<id>`, `get_vault_client()` (lru_cache singleton), `_VaultReader` Protocol, and `Authenticate` class. The `__call__` order is: header parse → DB hash lookup → revoked check → Vault raw cross-check (timing-safe via `secrets.compare_digest`) → scope check → `touch_last_seen` → return row.
- `tests/_auth.py` (new): `StubVault` (`get_secret`/`put_secret`/`list_keys` against an in-process dict) + `issue_test_key(*, vault, scopes=None, label="test") -> (raw_key, headers)` for every downstream auth-using test.
- `tests/unit/test_auth.py` (new): the eight planned scenarios — no header / wrong scheme / unknown / revoked / missing scope / valid+touch / admin scope passes / Vault mismatch.
- `docs/vault.md` (new): wiring, `secret/api-keys/<id>` path layout, issuance + revoke flow (forward-references Task 2), ASCII auth-resolution diagram, operator notes.

**Refinements / deviations.**

1. **`Authenticate.__call__`'s `vault` parameter typed as a `_VaultReader` Protocol**, not the concrete `VaultClient`. Tests inject a `StubVault` directly; without the Protocol, mypy rejected eight call sites. The Protocol exposes only `get_secret` since that's all `Authenticate` consumes; `VaultClient` satisfies it structurally — no behavioural change.
2. **`StubVault` ships without `delete_secret`** even though the planned scope listed it. `functions/vault.py::VaultClient` doesn't have a delete method either, and adding both now would only be exercised in Task 2's revoke script. Deferred to Task 2 so the real and stub gain the method together (interface stays in lockstep). Recorded in the `tests/_auth.py` module docstring.

**Side fix (not in original Task 1 scope).** User hit `make vault-status` → "server gave HTTP response to HTTPS client". Root cause: the `vault` CLI defaults to `VAULT_ADDR=https://127.0.0.1:8200`, but the dev-mode container serves plain HTTP. Fix in `makefile`: added a `VAULT_EXEC := docker exec -e VAULT_ADDR=http://127.0.0.1:8200 quake_vault` helper, routed `vault-status`/`vault-init`/`vault-unseal` through it; inlined the same env on `vault-seal` (which already needs an extra `-e VAULT_TOKEN=…`). Short comment block explains the why. `make vault-status` now returns the expected dev-mode envelope (`Initialized: true`, `Sealed: false`, `Storage Type: inmem`).

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 82 unit tests (8 new under `test_auth.py`) + 2 integration. Manual: `make vault-status` succeeds.

**Commit message (proposed).**

```
feat(auth): Authenticate dependency + Vault-backed API-key resolution

Adds quake/api/auth.py (hash_key, generate_raw_key, vault_path,
Authenticate), docs/vault.md, and a shared tests/_auth.py helper
(StubVault + issue_test_key). Endpoints opt in via
Depends(Authenticate()) or Depends(Authenticate(required_scope=...))
in later tasks.
```

---

### Task 2 — `make issue-api-key` + `make revoke-api-key` ✅

**Outcome.**

Shipped with two scoped additions and one small CLI deviation. Changes:

- `scripts/__init__.py` (new) — package marker.
- `scripts/issue_api_key.py` (new) — `issue(*, label, scopes, vault, stdout) -> key_id` core + argparse CLI (`--label`, `--scopes <comma>`). Inserts the DB row, puts the Vault payload `{raw_key, label, issued_at}`, prints `key_id` / `label` / `scopes` / "save this — it cannot be recovered" banner + the raw key on its own line. On Vault failure: hard-deletes the row.
- `scripts/revoke_api_key.py` (new) — `revoke(*, key_id, vault, stdout, stderr) -> int` core + argparse CLI (`--key-id`). Idempotent: re-runs print "already revoked"; unknown ids exit 2.
- `database/etls/api_keys.py` — added `get_by_id(id)` (needed for revoke's idempotency check) and `delete(id)` (used by issue's rollback path; distinct from `revoke` which leaves a tombstone).
- `functions/vault.py` — added `delete_secret(path)` via `delete_metadata_and_all_versions` so the raw value can't be recovered from version history. Idempotent (missing path → no-op).
- `tests/_auth.py` — `StubVault.delete_secret(path)` mirroring the real client.
- `makefile` — `issue-api-key` and `revoke-api-key` targets under a new "API-key issuance / revocation" section. Both source `.env`; revoke requires `KEY_ID` and prints usage if missing. **Removed** the pre-existing Epic-5 placeholder stubs at lines 263-268 ("`(stub) not yet implemented`") that were shadowing the real targets — `make check` emitted "overriding recipe" warnings before the cleanup.
- `tests/unit/test_api_key_scripts.py` (new) — six tests: DB+Vault writes, single raw-key print, rollback on Vault failure, revoke happy path, idempotency message, unknown-id exit code.

**Deviations from spec.**

1. **Revoke takes `--key-id` only, not `--label`.** Plan said "KEY_ID or LABEL if unique"; labels aren't `UNIQUE` in the schema, so "if unique" needs a count query + ambiguous-error path that adds material complexity. The `key_id` is in the issue output anyway. Trivial to add label lookup if you want it.
2. **Two extra ETL methods** (`ApiKeysETL.get_by_id`, `ApiKeysETL.delete`) and **one extra Vault method** (`VaultClient.delete_secret`). All directly required by the script logic; no speculative surface added. Inline docstrings explain the why.

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 88 unit tests (6 new under `test_api_key_scripts.py`) + 2 integration. Manual: live `make issue-api-key LABEL=dev` was not exercised in this task but will be by the integration smoke in Task 7.

**Commit message (proposed).**

```
feat(scripts): make issue-api-key and make revoke-api-key

Issuance generates qkf_<hex32>, persists the hash in quake.api_keys,
stores the raw value at secret/api-keys/<id>, prints raw once.
Revoke flips revoked_at and destroys the Vault path. Both idempotent
where it makes sense.

Adds ApiKeysETL.get_by_id + delete and VaultClient.delete_secret to
support the script flows; removes the old (stub) makefile entries.
```

---

### Task 3 — Retrofit `/events*` with `Authenticate()` ✅

**Outcome.**

Shipped as planned, plus one transitively-required update to the integration smoke. Changes:

- `quake/api/events/main.py`: `EventsManager.__init__` now constructs the router with `dependencies=[Depends(Authenticate())]` (router-level, no scope). One change, both routes inherit.
- `tests/unit/test_events_api_recent.py` and `tests/unit/test_events_api_query.py`:
  - `client` fixture wraps the existing setup with `StubVault` + `app.dependency_overrides[get_vault_client]` + `issue_test_key(...)` + `c.headers.update(headers)`. Every previously-passing assertion keeps working unchanged.
  - New `no_auth_client` fixture (same Vault override, no header) for negative tests.
  - Two new tests per file: `*_requires_auth` (no header → 401) and `*_rejects_bad_key` (well-formed but unknown key → 401).
- `tests/unit/test_main_api.py`: module docstring expanded to call out that `/health` / `/metrics` / `/env` are intentionally public and the fixture's lack of an `Authorization` header is a load-bearing regression guard.
- `tests/integration/test_read_api.py`:
  - Auth imports + StubVault override + issued key folded into the `client` fixture.
  - `client` now depends on `clean_events` so the TRUNCATE runs **before** the key is issued (without that, the truncate wiped the row and every protected request 401'd). Test function signature dropped its now-redundant `clean_events` parameter; a comment notes the transitive dep.
  - `quake.api_keys` added to the integration TRUNCATE set so issued keys don't leak across runs.

**Deviation from spec.** Plan only listed the two unit-test files. The integration smoke broke transitively when `/events*` went protected; updated with the same StubVault-override + pre-loaded-header pattern rather than letting Task 7 inherit a broken intermediate state.

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 92 unit tests (4 new under `/events*` for the 401 cases) + 2 integration.

**Commit message (proposed).**

```
feat(api): require API key on /events and /events/recent

Wires Depends(Authenticate()) at the EventsManager router level.
Public endpoints (/health, /metrics, /env) stay open. Test fixtures
issue a sandbox-DB-backed key via tests/_auth.py; the integration
smoke gets the same StubVault override.
```

---

### Task 4 — `EndpointLocksETL` + `poll_usgs` gating ✅

**Outcome.**

Shipped as planned, no behavioural deviations. Changes:

- `database/etls/endpoint_locks.py` (new) — `EndpointLocksETL` with `list_all`, `is_locked`, `set_lock`, `clear_lock`. `set_lock` / `clear_lock` return `EndpointLockRow | None` (None on unknown name → Task 5's view layer translates to 404). `is_locked` fails open on unknown names; rationale in the module docstring (a missing row is a code bug, not operator state, and the ingestion path prefers to keep running over silently halting on a typo).
- `database/etls/ingestion_runs.py` — added `record_skipped(reason) -> int` — atomic INSERT with `started_at=finished_at=now()`, counts at 0, `error=reason`. Returns the new id for parity with `start_run`.
- `quake/events/ingest.py` — at the top of `poll_once`, before any `UsgsClient` construction, check `EndpointLocksETL().is_locked(_INGESTION_LOCK)`; if locked, call `runs_etl.record_skipped(_LOCK_SKIP_REASON)`, log the skip with the run id, return `IngestionResult(0, 0, 0, error=_LOCK_SKIP_REASON)`. Module-level constants `_INGESTION_LOCK = "INGESTION_LOCK"` and `_LOCK_SKIP_REASON = f"{_INGESTION_LOCK} active"` factor out the literals so Tasks 5/7 can reference the same names.
- `tests/unit/test_endpoint_locks_etl.py` (new) — 8 tests: seeded-lock visibility, `is_locked` for seeded / unknown / set / cleared, `set_lock` on existing row, `set_lock` on unknown name → None, `clear_lock` resets fields + idempotent, `clear_lock` unknown → None, repeated `set_lock` overwrites (locked_by / reason latest-wins).
- `tests/unit/test_ingest.py` — added `test_poll_skips_when_ingestion_lock_set`. Tracks fetch calls via a monkeypatched `UsgsClient.fetch`; asserts the call list stays empty (USGS never contacted) and the skip envelope lands in both the return value and the `ingestion_runs` row.

**Verification.** `make check` clean (isort/black/flake8/mypy/bandit/pyright). `make test` passes — 101 unit tests (8 new under `test_endpoint_locks_etl.py` + 1 new in `test_ingest.py`) + 2 integration.

**Commit message (proposed).**

```
feat(ingest): EndpointLocksETL + poll_usgs gating on INGESTION_LOCK

When the lock is set, poll_once writes a skip-marker ingestion_runs
row (via the new IngestionRunsETL.record_skipped) and returns without
constructing a UsgsClient. /admin/locks (next task) is the operator
surface for setting/clearing.
```

---

### Task 5 — `/admin/locks` Manager + Views (admin-scoped)

**Scope.**

- New `quake/api/locks/main.py`: `LocksManager` with `APIRouter(prefix="/admin/locks")`. `dependencies=[Depends(Authenticate(required_scope="admin"))]` applied **at the router level** so every route inherits admin scope without per-route repetition.
- New `quake/api/locks/views.py`: `LocksManagerViews` with `list_locks()`, `set_lock(lock_name: str, body: SetLockRequest)`, `clear_lock(lock_name: str)`.
- New `quake/api/locks/models.py`: `LockResponse` (mirror `EndpointLockRow`), `SetLockRequest(locked_by: str | None = None, reason: str | None = None)`, `LocksListResponse(count: int, locks: list[LockResponse])`.
- `quake/main.py`: mount `LocksManager`.
- New `tests/unit/test_locks_api.py`:
  - `test_list_locks_admin` — admin key → 200, returns seeded `INGESTION_LOCK`.
  - `test_set_lock_admin` — POST → 200, body returns updated row, DB confirms.
  - `test_clear_lock_admin` — DELETE → 200, DB confirms.
  - `test_unknown_lock_set_is_404` — POST to a name with no row → 404 (or auto-create? **proposed: 404 — locks are seeded by migration**; document choice).
  - `test_no_key_is_401`
  - `test_non_admin_key_is_403`

**Acceptance.**

- `make check` clean.
- `make test` passes.

**Commit message (proposed).**

```
feat(api): /admin/locks (admin-scoped) for runtime kill switches

GET lists every endpoint_locks row; POST /{name} sets locked_by/reason
and is_locked=true; DELETE /{name} clears. Router-level admin scope.
```

---

### Task 6 — `/admin/ingest/*` Manager + Views (admin-scoped, async trigger)

**Scope.**

- New `quake/api/ingest/main.py`: `IngestManager` with `APIRouter(prefix="/admin/ingest")`, router-level `Authenticate(required_scope="admin")`.
- New `quake/api/ingest/views.py`:
  - `trigger()` — `task = poll_usgs.delay()`; returns `TriggerResponse(task_id=task.id, queued_at=datetime.now(timezone.utc))`.
  - `status(limit: int = 10)` — `IngestionRunsETL().latest(limit)`, returns `IngestStatusResponse(count, runs)`.
- New `quake/api/ingest/models.py`: `TriggerResponse`, `IngestRunResponse` (mirror `IngestionRunRow`), `IngestStatusResponse`.
- `quake/main.py`: mount `IngestManager`.
- New `tests/unit/test_ingest_api.py`:
  - `test_trigger_enqueues_task` — monkey-patch `poll_usgs.delay` to return a stub `AsyncResult`-like object; admin key → 200; body contains a non-empty `task_id`.
  - `test_status_returns_latest_runs` — seed two `ingestion_runs` rows; admin key → 200; rows in DESC order.
  - `test_trigger_requires_admin_scope` — non-admin key → 403.
  - `test_status_requires_auth` — no key → 401.

**Acceptance.**

- `make check` clean.
- `make test` passes.

**Commit message (proposed).**

```
feat(api): /admin/ingest/trigger + /admin/ingest/status (admin-scoped)

trigger enqueues poll_usgs.delay() and returns {task_id, queued_at};
status returns the latest ingestion_runs (DESC). Router-level admin
scope.
```

---

### Task 7 — Integration smoke — end-to-end auth + admin

**Scope.**

- New `tests/integration/test_auth_admin.py`:
  - Per-test `clean_admin_state` fixture: truncate `quake.api_keys`, `quake.events`, `quake.event_revisions`, `quake.ingestion_runs`; reseed `INGESTION_LOCK` clear.
  - One end-to-end test function exercising:
    - Issue a "read" key (no scopes) → 200 on `/events/recent`, 403 on `/admin/locks`.
    - Issue an "admin" key (`["admin"]`) → 200 on both.
    - With admin key, `POST /admin/locks/INGESTION_LOCK` → 200, lock is set.
    - `POST /admin/ingest/trigger` → 200, returns `task_id`. With Celery in eager mode (configured at test-setup), the task runs synchronously and writes a skip-marker `ingestion_runs` row (because the lock is set).
    - `DELETE /admin/locks/INGESTION_LOCK` → 200.
    - `POST /admin/ingest/trigger` again → 200; this time the task actually fetches USGS (or the test stubs the HTTP layer — **decision: stub at the `UsgsClient` level via the same approach used in `tests/unit/test_ingest.py`** to keep the integration test offline-capable and deterministic).
    - Revoke the admin key → `/admin/locks` now returns 401.

**Acceptance.**

- `make check` clean.
- `make test` passes (integration suite runs as part of `make test`).

**Commit message (proposed).**

```
test(integration): end-to-end auth + admin surface

Issues read + admin keys; verifies the scope ladder; toggles
INGESTION_LOCK and confirms poll_usgs skip-vs-run behaviour through
the /admin/ingest endpoints; revokes a key and confirms 401.
```

---

## After all tasks ship

- User confirms commit range, then asks Claude to:
  - Mark Epic 5 ✅ Done in `MASTER_PLAN.md` with the commit range.
  - Optionally archive this `PLAN.md` to `docs/history/epic-05-auth-admin.md` (skipped at the user's discretion as in Epic 4).
- Root `PLAN.md` slot is then free for Epic 6.
