# MASTER_PLAN.md — quake-feed

Epic-level roadmap for the project. Each epic, when it becomes the active one, gets its own `PLAN.md` at the repo root that breaks it into PR-sized steps. `PLAN.md` is gitignored — it's a local working doc between Claude and the user.

---

## Methodology

The workflow exists so the user retains **100% ownership** of every commit. Full spec lives in [`CLAUDE.md`](CLAUDE.md) under "Development Methodology"; the short version:

1. **Pick the next epic** from the list below. Move its status to `🟡 In progress`.
2. **Claude drafts `PLAN.md`** at the repo root, breaking the epic into ordered tasks. **Each task = one commit.** Claude then stops and waits for the user to review the plan (and request revisions if needed).
3. **One task at a time.** Only when the user explicitly prompts for a task ("proceed with task N") does Claude implement it. Claude runs `make check` + `make test`, then stops with a summary and a proposed commit message. The user reviews, commits, and pushes.
4. **Claude never runs state-changing git commands** (no `add`, `commit`, `push`, `reset`, `checkout`, `branch`, etc.). Read-only (`status`, `diff`, `log`, `show`, `blame`) is fine for situational awareness.
5. **`PLAN.md` updated on request** after each pushed commit — progress table + outcome record.
6. **Epic complete** → mark `✅ Done` here with the commit range, delete (or archive) the per-epic `PLAN.md`.

**Status legend:** `⬜ Not started` · `🟡 In progress` · `✅ Done` · `⏸ Deferred`

---

## Epics

| # | Epic | Status | Notes |
|---|------|--------|-------|
| 1 | Repo scaffold + Docker Compose + CI stub | ✅ Done | The structural skeleton — no business logic yet. Commits `dca18b0..b225ab7`. |
| 2 | Database layer (dbmate, baseline migration, ETL helpers) | ✅ Done | Baseline migration + sandbox-test CI + connection pool + Pydantic row models + ETLs for events/revisions/ingestion_runs/api_keys/alert_filters + pretty-schema helper. Commits `065ce98..27d4b40`. |
| 3 | USGS ingestion worker | ✅ Done | USGS HTTP client + GeoJSON parser + ingestion orchestrator + Celery `poll_usgs` (Beat every 60s) + `health_check` + self-hosted integration smoke. Commits `bb1c583..b4c5d96`. |
| 4 | Read API (events endpoints) | ✅ Done | `EventResponse` DTO + `EventsQuery` validators + `EventsETL.query()` combined-filter SQL + `EventsManager` mounting `/events/recent` and `/events` (with `near=lat,lon`, `radius_km`, `min_magnitude`, `since`, `limit`) + `MainManager` `/metrics` + `/env` + end-to-end integration smoke. Commits `b43d8cb..7dc8c5c`. |
| 5 | API-key auth + admin surface | ⬜ Not started | `Authenticate` dependency, Vault-backed key set, admin scope, locks endpoint. |
| 6 | SSE alerts (`/alerts/stream`) | ⬜ Not started | In-process pub/sub, per-key persistent filters, filter matcher. |
| 7 | Frontend (React + Vite + TypeScript + Leaflet) | ⬜ Not started | Live map, recent-events timeline, alert-config form. |
| 8 | Observability (Prometheus metrics + Grafana dashboard) | ⬜ Not started | Ingestion success/latency metrics, provisioned dashboard. |
| 9 | Documentation polish + architecture diagram + demo GIF | ⬜ Not started | README finalization; `docs/architecture.md`. |

> Final publication (pinning the repo on GitHub, any external listing) is a user action, not a Claude task — intentionally not an epic here.

---

## Epic 1 — Repo scaffold + Docker Compose + CI stub

**Deliverable.** A `make up` that starts the full container set (backend, worker, beat, postgres+timescale, rabbitmq, vault, prometheus, grafana, loki) with stub endpoints. Static-analysis CI workflow runs `make check` on push.

**In scope.**
- Directory skeleton matching the structure in `CLAUDE.md`.
- `pyproject.toml`, `setup.cfg`, `pytest.ini` with tool configs (line length 120, py314, black/isort/flake8/mypy/bandit/vulture).
- `requirements.txt`, `requirements-dev.txt`, `requirements-test.txt`.
- `docker-compose.yml` with all services and named volumes; one `Dockerfile` (shared by backend, worker, beat).
- `makefile` with every target listed in `CLAUDE.md` (dev/test/check/format/up/down/migrate/vault).
- `.env.template` and `make install-env`.
- `__main__.py`, `__metadata__.py`, `config.py` (Celery app), `quake/main.py` (stub FastAPI app with one health endpoint).
- `functions/environment.py` (Pydantic Settings), `functions/logger.py`, `functions/vault.py`, `functions/scheduler.py`, `functions/celery_metrics.py`.
- `.github/workflows/code_quality_assurance.yml` running `make check` + `make test` on push.
- Pre-commit config.
- `.gitignore` (must include `PLAN.md`, `vault_init_output.txt`, `database/schema.sql`, `.env`).

**Out of scope.** Any earthquake business logic; database schema beyond an empty `quake` schema in the baseline migration (that's Epic 2).

---

## Epic 2 — Database layer

**Deliverable.** `make db-migrate` applies a versioned baseline migration that creates the `quake` schema, hypertables, and supporting tables. `make migrate-test` passes on the sandbox container.

**In scope.**
- `database/migrations/YYYYMMDDHHMMSS_baseline.sql` with: `quake` schema, `events` hypertable (TimescaleDB), `event_revisions`, `alert_filters`, `api_keys`, `endpoint_locks`, `ingestion_runs`. Each with `IF NOT EXISTS` guards.
- `database/main.py` — connection management + `transaction()` context manager.
- `database/models.py` — DB row models (dataclasses or Pydantic).
- `database/etls/` — `events.py`, `revisions.py`, `alert_filters.py`, `api_keys.py`, `ingestion_runs.py`. Each with `ExtractTransformLoad` subclass + parameterized SQL.
- `database/_pretty_schema.py` for `make db-schema`.
- `database/.dbmate.yml` (reference only; flags passed explicitly in the makefile).
- The sandbox-test target wired into CI.

---

## Epic 3 — USGS ingestion worker

**Deliverable.** Every 60 seconds the worker pulls the USGS realtime feed, upserts events, records a row in `ingestion_runs`, and writes a revision row when magnitude or depth changes meaningfully.

**In scope.**
- `quake/ingestion/usgs/` — HTTP client with retries/backoff, GeoJSON parser, mapping to internal `Event` model.
- `quake/events/` — business logic: dedupe on `event_id`, decide whether a change is a revision (noise-threshold constants), upsert path.
- `quake/tasks.py` — `poll_usgs` task; Celery Beat schedule entry; `health_check` task.
- Unit tests covering: parse, upsert, revision-vs-noop decision, ingestion-run accounting.
- Integration test: spin up the stack, run the task once, assert events land in the DB.

---

## Epic 4 — Read API

**Deliverable.** Three GET endpoints under `/events` with OpenAPI docs.

**In scope.**
- `quake/api/events/` — Manager + Views + Pydantic request/response models.
- Endpoints: `/events/recent?limit=N`, `/events?near=lat,lon&radius_km=R`, `/events?min_magnitude=X&since=T`. Query-param validation with Pydantic.
- `quake/api/main/` — health, `/metrics`, running env.
- Tests: per-endpoint unit tests against a seeded DB.

---

## Epic 5 — API-key auth + admin surface

**Deliverable.** Protected endpoints require `Authorization: Bearer <key>`. `make issue-api-key` writes a new key to Vault and prints it once. Admin endpoints require an additional `admin` scope.

**In scope.**
- `quake/api/auth.py` — `Authenticate` dependency; key lookup against `api_keys` (hash) cross-checked with the Vault-stored raw key set; scope check.
- `make issue-api-key`, `make revoke-api-key` targets.
- `quake/api/locks/` — Manager + Views for `/admin/locks` (kill-switch flags); admin-scoped.
- `quake/api/ingest/` — Manager + Views: `/admin/ingest/trigger`, `/admin/ingest/status`; admin-scoped.
- `docs/vault.md` — secret layout for API keys.

---

## Epic 6 — SSE alerts

**Deliverable.** `/alerts/stream` keeps a long-lived SSE connection per client, gated by their API key. The ingestion worker publishes new events to an in-process asyncio queue inside the API process; the subscriber registry routes each event to matching subscribers.

**In scope.**
- `quake/alerts/` — `SubscriberRegistry` (per-key subscribers + their active filter), `FilterMatcher` (matches an event against a filter), in-process publisher hooked into the upsert path.
- `quake/api/alerts/` — Manager + Views for `/alerts/stream` (SSE), `/alerts/filters` (CRUD on persistent filters per API key).
- `models/alerts.py` — `AlertFilter`, `AlertEnvelope`.
- `docs/alerts.md` — design note: in-process pub/sub (no RabbitMQ fanout), single-pod by design, filter semantics.
- Tests: filter match cases, subscriber teardown on disconnect.

**Known limit.** Single-pod fanout only. If we ever scale beyond one backend pod, the publisher must move behind a broker (RabbitMQ) to fan out across pods. Local-only deployment makes the in-process design fine for now.

---

## Epic 7 — Frontend

**Deliverable.** A React + Vite + TypeScript app served at `/` by the backend, with three views: live map (Leaflet), recent-events timeline, alert-config form.

**In scope.**
- `frontend/` — Vite + React + TS scaffold; Tailwind or vanilla CSS (decide in `PLAN.md` for this epic).
- Typed API client generated from / aligned with the FastAPI OpenAPI spec.
- Map view subscribing to `/alerts/stream` for live updates.
- Recent-events timeline calling `/events/recent`.
- Alert-config form: choose min magnitude + geographic filter; persists via `/alerts/filters`.
- `make frontend-install`, `make frontend-dev`, `make frontend-build`. Production build copied into the backend image at build time.

---

## Epic 8 — Observability

**Deliverable.** Prometheus scrapes the backend; Grafana shows an ingestion-health dashboard checked into the repo.

**In scope.**
- `/metrics` endpoint via `prometheus_client` (already stubbed in Epic 1).
- Custom metrics: `usgs_poll_seconds`, `usgs_poll_errors_total`, `events_inserted_total`, `events_updated_total`, `sse_connections_active`.
- `monitoring/prometheus.yml` scrape config (already in Epic 1; this epic adds the metric definitions on the app side).
- `monitoring/grafana/dashboards/ingestion.json` — provisioned dashboard.
- `monitoring/grafana/provisioning/` for datasources + dashboard discovery.
- Loki tail of structured logs.

---

## Epic 9 — Documentation polish

**Deliverable.** README has a real demo GIF, the architecture diagram exists, and every `docs/` page referenced from README.md and CLAUDE.md is filled in.

**In scope.**
- `docs/architecture.md` — diagram (ASCII or PNG generated from a Mermaid source) + data-flow walkthrough.
- `docs/database-migrations.md` — dbmate workflow, sandbox-test, gotchas.
- `docs/vault.md` — Vault lifecycle, secret layout, unseal procedure.
- `docs/task-scheduler.md` — Celery + RabbitMQ + Beat schedule.
- `docs/alerts.md` — SSE design (mostly written in Epic 6; finalize here).
- README: insert demo GIF, fill the "What this demonstrates" table with concrete commit / file references where useful.
- Final pass: dead-link check, screenshot freshness.

---

## Decisions log

| Decision | Choice | When | Why |
|----------|--------|------|-----|
| Auth model | API-key only (no user accounts) | 2026-05-16 | Local-only deployment, no Supabase. Manager/Views auth pattern preserved via a single `Authenticate` dep. |
| Secrets store | HashiCorp Vault (dev-mode container) | 2026-05-16 | Keeps secrets out of `.env` files; API keys + DB password live there. |
| Alerts transport | SSE with in-process asyncio pub/sub | 2026-05-16 | No RabbitMQ fanout — single-pod by design. RabbitMQ stays in the stack for Celery ingestion only. |
| Frontend stack | React + Vite + TypeScript + Leaflet | 2026-05-16 | Committed up front (deferred in the source plan). |
| Cloud / hosting | None — local docker-compose only | 2026-05-16 | Explicit project constraint. |
| ML in this repo | None | 2026-05-16 | Out of scope; this repo focuses on data ingestion, serving, and observability. |
| EMSC fallback feed | Deferred | 2026-05-16 | USGS alone is enough for the demo. Revisit if USGS coverage proves insufficient. |
