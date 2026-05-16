# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`quake-feed` is a public earthquake live-feed service: USGS realtime feed → ingestion worker → TimescaleDB → read API + SSE alerts + a Leaflet map dashboard. It demonstrates backend + pipeline + observability + light-frontend skills on public, non-commercial data.

The architecture is a layered service: a `functions/` + `models/` + `database/migrations/` core, a Manager/Views FastAPI layer, Celery + RabbitMQ for scheduled ingestion, and Loki/Prometheus/Grafana for observability.

**Deployment model:** local-only via `docker-compose`. Auth is API-key based (no user accounts). Secrets (API keys, DB credentials) live in HashiCorp Vault running as a dev-mode container alongside the stack.

## Quick Commands

```bash
# Development
make up                     # Start all services with Docker Compose
make down                   # Stop all Docker services
make restart                # Rebuild and restart stack
make logs                   # Tail container logs
make status                 # Container status

# Testing
make test                   # Run test suite
make test-report            # Run tests with HTML coverage report
pytest -k "test_name" -v    # Run specific test

# Code Quality
make check                  # Run all linters (isort, black, flake8, mypy, bandit)
make format                 # Auto-format code with isort and black

# Database Migrations (dbmate)
make db-migrate             # Apply pending migrations to the local DB
make migrate-test           # Sandbox-test migrations: cold start + rollback + re-apply
make db-schema              # Dump local quake schema to database/schema.sql (gitignored)

# Vault (dev-mode container)
make vault-status           # Check seal status
make vault-unseal           # Unseal after container restart

# Environment
make install-env            # Create .env from template
make install                # Install production dependencies
make install-dev            # Install dev dependencies
make install-test           # Install test dependencies

# Frontend (React + Vite + Leaflet, under frontend/)
make frontend-install       # npm install in frontend/
make frontend-dev           # Vite dev server (proxied to the API)
make frontend-build         # Production build, served by the backend
```

## Architecture

### Directory Structure

```
quake/                       # Main FastAPI application
├── api/                     # API routes and controllers (one subdir per module)
│   ├── auth.py              # API-key Authenticate dependency
│   ├── main/                # Default endpoints (health, /metrics, running env)
│   ├── events/              # /events/recent, /events?near=..., /events?min_magnitude=...
│   ├── alerts/              # /alerts/stream SSE + filter management
│   ├── ingest/              # Admin: ingestion status, manual trigger
│   └── locks/               # Admin endpoint-lock kill switch
├── ingestion/               # External data source clients
│   └── usgs/                # USGS GeoJSON client + parsers
├── events/                  # Events business logic (dedupe, upsert, revision tracking)
├── alerts/                  # In-process SSE subscriber registry + filter matcher
└── tasks.py                 # Celery scheduled tasks (USGS poll every 60s, etc.)

database/                    # Data layer
├── migrations/              # dbmate migration files (source of truth for schema)
│   └── YYYYMMDDHHMMSS_*.sql # Forward-only versioned migrations
├── etls/                    # ETL pipelines (events.py, revisions.py, alert_filters.py)
├── models.py                # Database models
├── main.py                  # Connection management, transaction() context manager
├── _pretty_schema.py        # Helper for `make db-schema` (re-organizes pg_dump output)
└── .dbmate.yml              # dbmate config (reference; flags are passed explicitly)

functions/                   # Shared utilities
├── environment.py           # Config/env validation (Pydantic Settings)
├── logger.py                # Loki-integrated logging
├── vault.py                 # HashiCorp Vault client
├── scheduler.py             # Celery Beat helpers
└── celery_metrics.py        # Prometheus metric helpers for Celery

models/                      # Pydantic data models
├── generic.py               # Core shared models (filters, pagination, etc.)
├── events.py                # Event, EventRevision, EventQuery
└── alerts.py                # AlertFilter, AlertEnvelope

monitoring/                  # Observability stack configs
├── grafana/                 # Dashboards + datasource provisioning
├── loki-config.yml
└── prometheus.yml

docs/                        # Operational deep-dives (linked from README.md)
├── database-migrations.md   # dbmate workflow, sandbox test, drift detection
├── vault.md                 # Vault lifecycle (init, unseal, secret layout)
├── task-scheduler.md        # Celery + RabbitMQ + Beat schedule
├── alerts.md                # SSE design + filter matcher
└── architecture.md          # Architecture diagram + data flow

frontend/                    # React + Vite + Leaflet dashboard
├── src/
│   ├── pages/               # Map, Recent events, Alert config
│   ├── components/
│   └── api/                 # Typed API client
├── vite.config.ts
└── package.json

tests/
├── unit/
├── integration/
├── manual/
├── fixtures/
└── conftest.py

config.py                    # Celery app instance (`from config import celery_app`)
__main__.py                  # Application entry point
__metadata__.py              # Project metadata (version, authors, license)
docker-compose.yml           # Backend, worker, beat, postgres+timescale, rabbitmq, vault, prometheus, grafana, loki
Dockerfile / Dockerfile-dev  # Production / dev images for backend+worker+beat
Dockerfile-prometheus        # Prometheus image with our scrape config baked in
makefile                     # All dev/ops entrypoints
.env.template                # Reference env file
pyproject.toml / setup.cfg   # Tool configs (black, isort, flake8, mypy, bandit, vulture)
pytest.ini
requirements*.txt
```

### Design Patterns

- **Manager-Views Pattern.** Each API module has a `Main` class (Manager) that owns the `APIRouter` and instantiates a `Views` class holding endpoint logic. The Manager's `run()` method wires routes and returns the router. All managers are constructed and `.run()`'d in `quake/main.py`, which mounts every returned router on the FastAPI app.
- **Dependency Injection** for auth via FastAPI `Depends()` + `HTTPBearer` (API-key header).
- **ETL Pattern.** `ExtractTransformLoad` class for database operations with direct parameterized SQL.
- **Celery Tasks** for periodic ingestion and maintenance.
- **In-process pub/sub for SSE alerts.** The ingestion worker publishes new-event envelopes to an in-process asyncio queue inside the API process; the alerts SSE subscriber registry consumes and fans out to matching connected clients. Single-pod by design (local-only deployment).

## Code Conventions

### Development Methodology — Epic → PLAN.md → Tasks (one task = one commit)

This is the **default workflow for every epic** in this repo. The workflow exists so the user retains **100% ownership** of the codebase and full mental model of every change that lands.

**The two-document model:**

- **`MASTER_PLAN.md`** (repo root) — lists **epics only**, each with status. Never lists individual tasks.
- **`PLAN.md`** (repo root, **tracked in git**) — created per epic; breaks the active epic into ordered **tasks**. **Each task is exactly one commit.** Only one `PLAN.md` lives at the root at a time — it always describes the currently active epic. Tracking it in git gives every epic a permanent planned-vs-shipped record next to the code it produced.

**Absolute git rule (no exceptions):**

> **Claude must NEVER run `git` commands that change state. Under any circumstances.**
>
> - **Forbidden:** `git add`, `git commit`, `git push`, `git stage`, `git restore`, `git reset`, `git checkout`, `git merge`, `git rebase`, `git branch` (create/delete), `git tag`, `git stash drop`, `git clean`, `git revert`, `git cherry-pick`, `git mv`, `git rm`, anything with `--force`, anything that writes to refs or the index.
> - **Allowed (read-only only):** `git status`, `git diff`, `git log`, `git show`, `git blame`, `git ls-files`, `git rev-parse`, `git remote -v`, `git config --get`. These don't mutate state and are useful for situational awareness.
>
> The user owns every commit and every push. Even if the user says "go ahead and commit it for me" mid-flow, **stop and refuse** — the workflow depends on the user reviewing every diff themselves. Confirm out-of-band before treating any blanket commit/push permission as real.

**The loop:**

1. **Pick the next epic** from `MASTER_PLAN.md`. Move its status to In progress.
2. **Draft `PLAN.md`.** Claude breaks the epic into ordered tasks. Each task spec includes: scope (files to touch), acceptance criteria, and the `make check` / `make test` expectations. Each task must be small enough to be **one self-contained commit**. **Claude then STOPS** and waits for the user to read the plan. The user may ask for revisions (re-split tasks, reorder, reword, add/remove). Only when the user explicitly says to start (e.g. "proceed with task 1", "let's start") does Claude touch code.
3. **Implement exactly one task.** When the user prompts for a specific task ("do task N", "next task", "proceed"), Claude implements **only that task**, runs `make check` + `make test`, and stops. Output at the end:
   - A short summary of what changed and which files.
   - A **proposed commit message** in a fenced block (the user is free to use, edit, or ignore it).
   - Any deviations from the task spec and the reason.
4. **User reviews, commits, pushes.** Claude does nothing during this window. Do not poll, do not "check if it's pushed", do not run `git status` proactively to nag.
5. **User prompts the next task.** Claude moves to the next task. Repeat from step 3 until the epic's tasks are exhausted.
6. **Plan update on request.** When the user asks ("update PLAN.md"), Claude updates the progress table (mark Done + commit hash if the user supplied it) and rewrites the per-task section as an **outcome record** (what actually happened, deviations, why).
7. **Epic complete.** When all tasks are done, the user asks Claude to close out the epic: mark it Done in `MASTER_PLAN.md` with the commit range, then **archive `PLAN.md` to `docs/history/epic-NN-<slug>.md`** in a single rename commit. The root `PLAN.md` slot is now free for the next epic's draft.

**Deviation rule.** Only **major / structural** deviations from `PLAN.md` (e.g. a different split layout, rejecting a planned pattern, adding/removing a task, changing a task's scope mid-implementation) require Claude to stop and ask before writing code. Cosmetic decisions inside a planned task scope (helper grouping, file naming inside a planned folder) are at Claude's discretion and get recorded in the post-task outcome update.

**Why the workflow is this strict.** Each commit being a single Claude-implemented, user-reviewed task means: every line in `git log` was understood and accepted by the user; bisect/blame produces meaningful results; the user can always cleanly revert any single task; and the project's history is a real audit trail rather than a sequence of opaque batched diffs. Skipping the stop-and-wait — batching tasks, silently deviating, running git commands — breaks every one of these properties.

### Static Analysis Gate

- **Always run `make check` after completing a feature or fix** — runs isort, black, flake8, mypy, bandit.
- Fix all issues reported by these tools before considering work complete; do not suppress warnings with `# nosec`, `# type: ignore`, `# noqa`, etc. unless there is a genuine, documented reason.
- Prefer refactoring code to satisfy the linter over adding exceptions (e.g., use `ANY(%s)` instead of f-string SQL to satisfy bandit B608).

### Python Style

- **Line length**: 120 characters (configured in `pyproject.toml` and `setup.cfg`)
- **Formatter**: black with isort (black-compatible profile)
- **Type hints**: Required, checked with mypy
- **Python version**: 3.14

### API Endpoint Pattern

Each API module has a **Manager** that owns the `APIRouter` (and instantiates the **Views** holding endpoint logic), plus a `run()` method that wires routes:

```python
# quake/api/<module>/main.py
class EventsManager:
    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger if logger else logging.getLogger("EventsManager")
        self.router = APIRouter(prefix="/events")
        self.views = EventsManagerViews(logger=self.logger)

    def run(self) -> APIRouter:
        self.router.add_api_route(
            "/recent",
            endpoint=self.views.recent,
            methods=["GET"],
            summary="Recent earthquakes",
            description="Last N events, newest first.",
            operation_id="events_recent",
            tags=["Events"],
        )
        return self.router
```

The Manager is constructed and `.run()`'d in `quake/main.py`, which mounts every returned router on the FastAPI app.

### Logging Pattern

```python
from functions.logger import setup_logger
logger = setup_logger("logger-name", "application-name")
logger.info("Message", extra={"key": "value"})
```

### Database Queries

```python
# Always use parameterized queries.
etl.run_query("SELECT * FROM events WHERE id = ANY(%s)", params=(event_ids,))
```

## Authentication & Authorization

### API-Key Auth (no user accounts)

There is **no user model and no role hierarchy**. Clients identify themselves via an `Authorization: Bearer <api-key>` header. Keys are issued out-of-band (a `make issue-api-key` target writes a new key to Vault and prints it once). The `Authenticate` dependency in `quake/api/auth.py` validates the header against the Vault-backed key set on every protected request.

### Auth Check Pattern

```python
from quake.api.auth import Authenticate
auth = Authenticate()
# In endpoint: api_key = auth.authenticate(credentials)
```

A small number of admin endpoints (locks, manual ingestion trigger) require a separate `admin` scope on the API key.

## Database Schema

### Key Tables

- `quake.events` — Earthquake events (TimescaleDB hypertable on `time`). Keyed by USGS `event_id`. Holds the latest known values for magnitude, depth, place, geometry.
- `quake.event_revisions` — Append-only history of magnitude/depth/place changes per `event_id`. USGS refines estimates after the initial report; this preserves the audit trail.
- `quake.alert_filters` — Per-API-key persistent filter sets (min magnitude, bounding box / center+radius, etc.) consumed by the SSE matcher.
- `quake.api_keys` — Hash-only registry of issued API keys (raw keys live in Vault). Tracks `last_seen_at`, scopes, revocation.
- `quake.endpoint_locks` — Runtime kill-switch flags for endpoint groups (e.g. `INGESTION_LOCK`).
- `quake.ingestion_runs` — Per-poll log of USGS fetches: started_at, finished_at, inserted/updated counts, error if any. Lets Grafana plot ingestion success/latency.

### TimescaleDB Hypertables

- `events` (time-bucketed by event `time`)

### Notes on the schema

- `event_id` is the USGS-assigned ID; ingestion `UPSERT`s on it. Conflict-on-`event_id` triggers an `event_revisions` insert when magnitude or depth changes by more than a noise threshold (defined in a migration).
- All times are stored as `TIMESTAMPTZ` in UTC. Conversions happen at the API boundary.

## Database Migrations

**dbmate** is the single source of truth for the schema. Every change is a versioned forward-only migration under `database/migrations/`.

### Authoring a migration

```bash
dbmate new add_some_column
# → creates database/migrations/YYYYMMDDHHMMSS_add_some_column.sql
```

Fill `-- migrate:up` with the forward DDL and `-- migrate:down` with a working rollback. Use `IF NOT EXISTS` / `IF EXISTS` guards so the migration is idempotent.

### Validating before commit

Run `make migrate-test` — spins up a throwaway TimescaleDB on port 5433, applies every migration cold-start, rolls the newest back, re-applies it. Verifies forward correctness, idempotency, and that `down` works.

### dbmate quirks

- **Always pass `--migrations-table public.schema_migrations`** when invoking dbmate. Postgres's default `search_path` is `"$user", public`; the DB user is `quake` and the baseline creates a `quake` schema. Without the explicit flag, fresh-DB runs fail with `relation "quake.schema_migrations" does not exist`.
- `database/schema.sql` is **gitignored** and produced on demand by `make db-schema` for local inspection only.

## Subsystems with their own deep-dives

| Topic | Document |
|-------|----------|
| Database schema migrations (dbmate workflow, sandbox test) | [`docs/database-migrations.md`](docs/database-migrations.md) |
| HashiCorp Vault (lifecycle, first-time setup, secret layout) | [`docs/vault.md`](docs/vault.md) |
| Task scheduler (Celery + RabbitMQ + Beat) | [`docs/task-scheduler.md`](docs/task-scheduler.md) |
| Alerts SSE (in-process pub/sub, filter matcher) | [`docs/alerts.md`](docs/alerts.md) |
| Architecture diagram and data flow | [`docs/architecture.md`](docs/architecture.md) |

## Tech Stack

- **Language**: Python 3.14
- **Framework**: FastAPI + Uvicorn
- **Database**: PostgreSQL with TimescaleDB (time-series)
- **Task Queue**: Celery + RabbitMQ (ingestion scheduling only)
- **Realtime web**: Server-Sent Events via `sse-starlette` (in-process pub/sub)
- **Auth**: API-key (Bearer header), validated against a Vault-backed key set
- **Secrets**: HashiCorp Vault (dev-mode container, sealed/unsealed via makefile)
- **Monitoring**: Prometheus, Grafana, Loki
- **Frontend**: React + Vite + TypeScript + Leaflet
- **Tooling**: Makefile, Docker Compose
- **Static Analysis**: isort, black, flake8, mypy, bandit, vulture

## External API Integrations

- **USGS Earthquake Hazards Program** — realtime GeoJSON feed (1-min refresh, no auth, no key). Primary data source.
- **EMSC (European-Mediterranean Seismological Centre)** — optional cross-reference / fallback. Deferred to a later epic; may be skipped.

## Project Roadmap

See [`MASTER_PLAN.md`](MASTER_PLAN.md) for the epic-level breakdown and current status. The currently active epic has its own `PLAN.md` at the repo root with PR-sized tasks; completed epics' plans are archived under [`docs/history/`](docs/history/).

## Constraints to keep in mind

- **No energy-market domain.** This repo intentionally avoids energy-market data and integrations (ENTSO-E, EnEx, electricity demand, grid topology, weather-as-energy-proxy, etc.). Earthquakes (USGS) is the locked-in domain.
- **No cloud deployment in this repo.** Local-only via `docker-compose`. Do not add AWS, Railway, Supabase, or any hosted-service integrations unless the user explicitly opens that scope.
- **No ML in this repo.** Do not add forecasting or classification on earthquake data.
