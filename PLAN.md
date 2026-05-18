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
| 3 | Retrofit `/events*` with `Authenticate()` (no scope) | `quake/api/events/main.py`, `tests/unit/test_events_api_recent.py`, `tests/unit/test_events_api_query.py` | ⬜ |
| 4 | `EndpointLocksETL` + `poll_usgs` gating on `INGESTION_LOCK` | `database/etls/endpoint_locks.py`, `quake/events/ingest.py`, `tests/unit/test_endpoint_locks_etl.py`, `tests/unit/test_ingest.py` | ⬜ |
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

### Task 2 — `make issue-api-key` + `make revoke-api-key`

**Scope.**

- New `scripts/issue_api_key.py`:
  - argparse: `--label <text>` (optional), `--scope <name>` (repeatable, e.g. `--scope admin`).
  - `generate_raw_key()`, `hash_key()`, `ApiKeysETL().insert(...)`, `VaultClient().put_secret(vault_path(id), {"raw_key": raw, "label": label, "issued_at": now_iso})`.
  - Stdout: prints the key_id, label, scopes, and the **raw key on its own line, once** with a "save this — it cannot be recovered" banner.
  - Exit code 0 on success, non-zero on Vault/DB failures (rollback DB insert on Vault failure to keep them consistent).
- New `scripts/revoke_api_key.py`:
  - argparse: `--key-id <int>` (or `--label <text>` if unique).
  - `ApiKeysETL().revoke(id)`, `VaultClient()` deletes the path (`hvac` v2 delete + destroy versions so the raw value is unrecoverable).
  - Idempotent: revoking an already-revoked key prints "already revoked" and exits 0.
- `makefile` targets:
  - `issue-api-key: ## Issue a new API key (writes hash to DB, raw to Vault). Args: LABEL, SCOPES (comma-separated).`
  - `revoke-api-key: ## Revoke an API key. Args: KEY_ID or LABEL.`
- New `tests/unit/test_api_key_scripts.py`:
  - Runs the script functions directly (no subprocess) against the sandbox DB + StubVault.
  - `test_issue_inserts_db_row_and_vault_path`
  - `test_issue_prints_raw_key_once`
  - `test_issue_rolls_back_db_on_vault_failure`
  - `test_revoke_marks_db_and_destroys_vault`
  - `test_revoke_is_idempotent`

**Acceptance.**

- `make check` clean.
- `make test` passes.
- Manual smoke (no automated assertion): `make issue-api-key LABEL=dev` against the live stack writes Vault + DB, prints the raw key.

**Commit message (proposed).**

```
feat(scripts): make issue-api-key and make revoke-api-key

Issuance generates qkf_<hex32>, persists the hash in quake.api_keys,
stores the raw value at secret/api-keys/<id>, prints raw once.
Revoke flips revoked_at and destroys the Vault path. Both idempotent
where it makes sense.
```

---

### Task 3 — Retrofit `/events*` with `Authenticate()`

**Scope.**

- `quake/api/events/main.py`: both routes (`/recent`, `""`) gain `dependencies=[Depends(Authenticate())]` (no scope).
- `tests/unit/test_events_api_recent.py` and `tests/unit/test_events_api_query.py`:
  - Update the existing `client` fixture (or add an `auth_client`) to issue a test key via `tests/_auth.py` and pass the `Authorization` header on every request.
  - Add per-file `test_*_requires_auth` cases hitting the routes **without** a header → 401, and with an obviously bad key → 401.
- `/health`, `/metrics`, `/env` stay open — explicit `test_main_api.py` assertion that no key is needed (already passes; just leave a comment so it doesn't regress).

**Acceptance.**

- `make check` clean.
- `make test` passes; every previously-passing `/events*` test still passes (now with an auth header), plus the new 401 cases.

**Commit message (proposed).**

```
feat(api): require API key on /events and /events/recent

Wires Depends(Authenticate()) onto both EventsManager routes. Public
endpoints (/health, /metrics, /env) stay open. Test fixtures issue a
sandbox-DB-backed key via tests/_auth.py.
```

---

### Task 4 — `EndpointLocksETL` + `poll_usgs` gating

**Scope.**

- New `database/etls/endpoint_locks.py`:
  - `list_all() -> list[EndpointLockRow]`
  - `is_locked(name: str) -> bool`
  - `set_lock(name: str, *, locked_by: str | None, reason: str | None) -> EndpointLockRow`
  - `clear_lock(name: str) -> EndpointLockRow` — flips `is_locked=false`, clears `locked_by`/`locked_at`/`reason`.
- `quake/events/ingest.py` (or wherever `poll_once` lives — verify): at the top, `if EndpointLocksETL().is_locked("INGESTION_LOCK"): IngestionRunsETL().record_skipped("INGESTION_LOCK active"); return IngestionRun(...skipped envelope...)`. The exact field choices documented in the design-choices section (error column carries the skip reason, counts stay zero).
- Extend `tests/unit/test_endpoint_locks_etl.py` (new file) with the four ETL methods.
- Extend `tests/unit/test_ingest.py` with `test_poll_skips_when_ingestion_lock_set` — seed lock, run `poll_once()`, assert: no USGS call, exactly one `ingestion_runs` row with the skip envelope.

**Acceptance.**

- `make check` clean.
- `make test` passes.

**Commit message (proposed).**

```
feat(ingest): EndpointLocksETL + poll_usgs gating on INGESTION_LOCK

When the lock is set, poll_usgs writes a skip-marker ingestion_runs row
and returns without touching USGS. /admin/locks (next task) is the
operator surface for setting/clearing.
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
