# PLAN.md — Epic 1: Repo scaffold + Docker Compose + CI stub

> **Status:** Draft, awaiting user review.
> **Source epic:** [`MASTER_PLAN.md`](MASTER_PLAN.md) → Epic 1.
> **Lifecycle:** This file is local-only (gitignored once Task 1 lands). Updated after each pushed commit per the [methodology in CLAUDE.md](CLAUDE.md#development-methodology--epic--planmd--tasks-one-task--one-commit).

---

## Epic goal

A `make up` brings the full container set online (backend, worker, beat, Postgres+Timescale, RabbitMQ, Vault, Prometheus, Grafana, Loki). The backend serves a `/health` endpoint. `make check` and `make test` pass on a freshly cloned repo. A GitHub Actions workflow runs both on push.

**Out of scope for this epic.** Any earthquake business logic (events table, USGS client, ingestion, alerts, frontend). Database schema beyond an empty `quake` schema is Epic 2.

---

## Task ordering rationale

Tasks are ordered so each commit leaves the repo in a sensible state:

1. **Root hygiene** lands first so `PLAN.md`, `.env`, `vault_init_output.txt`, etc. don't accidentally end up in commits.
2. **Tooling config** lands before any code so every subsequent task can be linted/typed consistently.
3. **Directory skeleton** establishes import paths so `functions/` and `quake/` can refer to each other.
4. **Shared utilities** are the foundation the entrypoints will import.
5. **App entrypoints** make the project runnable as a process (without containers).
6. **Dockerfiles** package the process into images.
7. **Docker Compose + monitoring** orchestrate the images plus stateful services.
8. **Makefile** ties all the above into one operator interface and becomes the workflow's `make check`/`make test` runner.
9. **CI workflow** locks in the static-analysis + test gate on every push.

> **Linting during tasks 3–7.** `make check` doesn't exist yet (Task 8 creates it). For those tasks, run the linters directly: `isort --check .`, `black --check .`, `flake8 .`, `mypy .`, `bandit -r -c pyproject.toml .`. From Task 8 onward, `make check` is the canonical command.

---

## Progress

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Root hygiene (`.gitignore`, `.env.template`) | ✅ Done | `dca18b0` |
| 2 | Python tooling config (`pyproject.toml`, `setup.cfg`, `pytest.ini`, `requirements*.txt`, `__metadata__.py`) | ✅ Done | `e4dd5fc` |
| 3 | Directory skeleton (empty `__init__.py` packages) | ✅ Done | `a8d08ca` |
| 4 | Shared utilities (`functions/`) | ⬜ Not started | — |
| 5 | App entrypoints (`config.py`, `quake/main.py`, `quake/api/main/`, `__main__.py`) | ⬜ Not started | — |
| 6 | Dockerfiles (`Dockerfile`, `Dockerfile-dev`, `Dockerfile-prometheus`) | ⬜ Not started | — |
| 7 | Docker Compose + monitoring configs | ⬜ Not started | — |
| 8 | Makefile | ⬜ Not started | — |
| 9 | CI workflow (`.github/workflows/code_quality_assurance.yml`) | ⬜ Not started | — |

**Status legend:** `⬜ Not started` · `🟡 In progress` · `✅ Done`
**Next:** Task 4.

---

## Task 1 — Root hygiene ✅

**Status:** Done · Commit `dca18b0`

**Shipped**
- `.gitignore` — Python (`__pycache__`, `*.pyc`, `.venv`, `*.egg-info`, `dist`, `build`, `htmlcov`, `.coverage`, `.mypy_cache`, `.pytest_cache`), Node (`node_modules`, `frontend/dist`), tooling (`.idea`, `.vscode`), env/secrets (`.env`, `.env.local`, `vault_init_output.txt`), generated artifacts (`database/schema.sql`), Docker overrides, editor/OS caches.
- `.env.template` — 21 env vars grouped by service (runtime, backend, database, logger, prometheus, grafana, rabbitmq, vault), all with safe local-docker-compose defaults.

**Verifications**
- `git check-ignore -v` confirms `.env`, `vault_init_output.txt`, `database/schema.sql`, `__pycache__/`, `node_modules/`, `.venv/` are caught.
- `set -a; source .env.template; set +a` parses cleanly.

**Deviations from original plan**
1. **Pre-commit hooks dropped.** Originally planned `.pre-commit-config.yaml` alongside `.gitignore`/`.env.template`. Removed after discussion: `make check` (Task 8) + GitHub Actions (Task 9) cover the same gate without duplicating tool versions or risking silent auto-modification of staged files. The "100% ownership of every diff" rule made pre-commit's auto-format-on-commit behavior a slight anti-pattern.
2. **`PLAN.md` is now tracked in git** (originally listed in `.gitignore`). Decision: a public portfolio repo benefits from a permanent planned-vs-shipped record next to the code; cross-machine continuity and session resilience also argued for tracking. `CLAUDE.md` and `MASTER_PLAN.md` were updated to match; epic-complete handoff is now "archive `PLAN.md` to `docs/history/epic-NN-<slug>.md`" rather than delete.

---

## Task 2 — Python tooling config ✅

**Status:** Done · Commit `e4dd5fc`

**Shipped**
- `pyproject.toml` — `[build-system]` (setuptools+wheel), `[tool.black]` (line-length 120, `target-version = ["py314"]`, exclude block), `[tool.bandit]` (excludes `.venv`, `tests`, `dist`, `build`, `frontend`), `[tool.vulture]` (paths `["."]`, ignore decorators for `@celery_app.task` / `@*.task` / `@*.connect`, min_confidence 80), `[tool.pyright]` (mirrors mypy for editor support).
- `setup.cfg` — `[isort]` (black profile, line-length 120, `known_first_party = quake,database,functions,models`), `[flake8]` (max-line-length 120, ignore `E203,W503`, per-file `__init__.py:F401`), `[mypy]` (`python_version = 3.14`, strict + `ignore_missing_imports`), `[mypy-tests.*]` (relaxes `disallow_untyped_defs`).
- `pytest.ini` — `testpaths = tests`, `pythonpath = .`, addopts `-ra --strict-markers --strict-config`, three markers (`unit`, `integration`, `manual`).
- `requirements.txt` — exact `==` pins (FastAPI 0.136.1, Uvicorn 0.47.0, Pydantic 2.13.4, pydantic-settings 2.14.1, psycopg[binary] 3.3.4, Celery 5.6.3, hvac 2.4.0, prometheus-client 0.25.0, python-json-logger 4.1.0, httpx 0.28.1, tenacity 9.1.4).
- `requirements-test.txt` — `-r requirements.txt` + linters (isort 8.0.1, black 26.3.1, flake8 7.3.0, mypy 2.1.0, bandit 1.9.4, vulture 2.16) + pytest stack (pytest 9.0.3, pytest-asyncio 1.3.0, pytest-cov 7.1.0, coverage-badge 1.1.2).
- `requirements-dev.txt` — `-r requirements-test.txt` + `ipython 9.13.0`.
- `__metadata__.py` — `__title__`, `__description__`, `__version__ = "0.1.0"`, `__license__ = "MIT"`. No personal-identifying details.

**Verifications (after user provisioned `.venv`)**
- All five linters run clean from `.venv/bin/<tool>`: isort exit 0 (2 files skipped — configs), black exit 0 (1 file unchanged), flake8 exit 0 (no issues), mypy exit 0 (1 source file checked), bandit exit 0 (5 LoC scanned, 0 issues).
- Installed tool versions match the pins exactly.

**Deviations from original plan**
1. **Exact `==` pins instead of `>=` floors.** User-driven choice during the task. Trades flexibility for full reproducibility.
2. **Linters moved from `requirements-dev.txt` to `requirements-test.txt`.** User-driven. Rationale: CI runs them, and CI is a test concern. `requirements-dev.txt` now contains only `ipython` on top of test (which transitively pulls runtime). This means `make install-test` will give CI everything it needs without dragging in `ipython`.
3. **`sentry-sdk` dropped entirely.** User decision: we won't use Sentry. Task 5's `config.py` scope was also amended to drop the planned Sentry init signal handler.
4. **`sse-starlette` commented out in `requirements.txt`.** Deferred until Epic 6 actually needs it (avoids carrying an unused dep through the early epics). Will be uncommented in Epic 6.
5. **`kombu` removed from explicit deps.** Celery pulls it transitively; no need to pin separately.
6. **`pytest-postgresql` not included.** Deferred per the plan's own "if we end up wanting it" note.
7. **`isort` config kept in `setup.cfg` only** (plan loosely listed it in both `pyproject.toml` and `setup.cfg`). Single source of truth.

---

## Task 3 — Directory skeleton ✅

**Status:** Done · Commit `a8d08ca`

**Shipped** — 27 files total
- 18 empty `__init__.py` markers for the `quake/` package tree (`quake/`, `quake/api/`, `quake/api/{main,events,alerts,ingest,locks}/`, `quake/ingestion/`, `quake/ingestion/usgs/`, `quake/events/`, `quake/alerts/`) plus `functions/`, `models/`, `database/`, `database/etls/`, and all five `tests/` packages (`tests/`, `tests/{unit,integration,manual,fixtures}/`).
- 1 empty `tests/conftest.py`.
- 8 `.gitkeep` placeholders: `database/migrations/`, `docs/`, `frontend/`, `monitoring/grafana/dashboards/`, `monitoring/grafana/provisioning/{datasources,dashboards}/`.

**Verifications**
- `python -c "import quake; import quake.api; …"` succeeds for all 14 importable package paths.
- All 5 linters pass: isort exit 0 (3 files skipped — configs), black exit 0 (22 files unchanged), flake8 exit 0, mypy exit 0 (22 source files), bandit exit 0.

**Deviations from original plan**
None. Files and directory layout match the plan exactly.

---

## Task 4 — Shared utilities (`functions/`)

**Why now.** The entrypoints (Task 5) import these; landing them first keeps Task 5 a pure wiring change.

**Files created**
- `functions/environment.py` — `EnvironmentalVariables` Pydantic Settings class with nested groups: `BackendConfig`, `DatabaseConfig`, `LoggerConfig`, `PrometheusConfig`, `GrafanaConfig`, `VaultConfig`, `RabbitMQConfig`. A `get_environmental_variables()` lru-cached accessor. Validates required vars at import-of-app time, not module import.
- `functions/logger.py` — `setup_logger(name: str, app_name: str) -> logging.Logger` that wires a JSON formatter (`python-json-logger`) and a Loki handler when `LOKI_HOST` is reachable; otherwise stdout-only. Idempotent.
- `functions/vault.py` — `VaultClient` (thin `hvac` wrapper) with `get_secret(path: str, key: str) -> str | None`, `put_secret`, `list_keys`. `init_vault(logger)` ensures the dev container is reachable and the KV mount `secret/` exists. No first-time-init heroics; Vault dev mode handles that.
- `functions/scheduler.py` — tiny helper: `crontab_or_default(env_var: str, default: str)` for reading cron strings from env at Beat-schedule build time.
- `functions/celery_metrics.py` — Prometheus counter/histogram registration for Celery task lifecycle (signal handlers on `task_prerun`, `task_postrun`, `task_failure`). Stub-quality at this stage; metrics get fleshed out in Epic 8.

**Acceptance**
- `python -c "from functions.environment import get_environmental_variables; from functions.logger import setup_logger; from functions.vault import VaultClient"` succeeds.
- `mypy functions/` is clean.

**Proposed commit message**
```
feat(functions): add env, logger, vault, scheduler, celery-metrics helpers
```

---

## Task 5 — App entrypoints

**Why now.** With `functions/` in place, this task wires a runnable FastAPI process. After this commit, `python -m` should boot the app to `/health` even without Docker.

**Files created**
- `config.py` — top-level Celery app instance (`celery_app = Celery(...)`); empty `beat_schedule` placeholder; broker URL composed from env. No signal handlers needed at this stage; tasks register on first task definition in Epic 3.
- `quake/main.py` — `Quake` class with `__init__(self, logger)` and `run(host, port)` (calls `uvicorn.run`). `__init__` builds the FastAPI app, mounts the single `MainManager` from `quake/api/main/`. Manager-Views pattern is in place from day one so we don't refactor later.
- `quake/api/main/main.py` — `MainManager` (owns `APIRouter()`, instantiates `MainManagerViews`, registers `/health` route).
- `quake/api/main/views.py` — `MainManagerViews` with a single async `health()` returning `{"status": "ok", "service": "quake-feed", "version": __version__}`.
- `quake/api/main/models.py` — `HealthResponse` Pydantic model.
- `__main__.py` — bootstrap: loads env, sets up logger, (optionally) pings Vault, constructs `Quake(logger)`, calls `.run(host, port)`.

**Acceptance**
- `python __main__.py` starts the server on `0.0.0.0:8000` (or whatever `.env` says) and `curl localhost:8000/health` returns the JSON.
- `make check`-equivalent (manual isort/black/flake8/mypy/bandit) passes.

**Proposed commit message**
```
feat: add FastAPI entrypoint with /health and Manager/Views scaffold
```

---

## Task 6 — Dockerfiles

**Why now.** The app runs locally; package it before Compose can use it.

**Files created**
- `Dockerfile` — production image. `python:3.14-slim` base, system deps for `psycopg` (`libpq-dev`, `build-essential`), copy `requirements.txt`, `pip install`, copy source, non-root `appuser`, `CMD ["python", "__main__.py"]`.
- `Dockerfile-dev` — dev image. Same base, installs `requirements-dev.txt` + `requirements-test.txt` on top of runtime, leaves source mounted via volume in Compose (no `COPY .` for the app code).
- `Dockerfile-prometheus` — Prometheus image with `monitoring/prometheus.yml` baked in. Tiny, just `FROM prom/prometheus:v2.46.0` + `COPY monitoring/prometheus.yml /etc/prometheus/prometheus.yml`.

**Acceptance**
- `docker build -t quake-feed:dev -f Dockerfile-dev .` succeeds.
- `docker build -t quake-feed:prod -f Dockerfile .` succeeds.
- `docker build -t quake-prometheus -f Dockerfile-prometheus .` succeeds (requires `monitoring/prometheus.yml`, which Task 7 creates — so this docker-build acceptance check may be deferred to after Task 7; just verify the Dockerfile parses with `docker build --check` or `hadolint` if available).

**Proposed commit message**
```
build: add Dockerfiles for backend (prod + dev) and Prometheus
```

---

## Task 7 — Docker Compose + monitoring configs

**Why now.** Images exist; orchestrate them.

**Files created**
- `docker-compose.yml` — services: `backend` (uses `Dockerfile-dev`, mounts the source), `celery_worker` (same image, runs `celery -A config.celery_app worker`), `celery_beat` (same image, runs `celery -A config.celery_app beat`), `postgres` (`timescale/timescaledb:latest-pg18`), `rabbitmq` (`rabbitmq:3-management`), `vault` (`hashicorp/vault:1.21.1` in dev mode), `prometheus` (uses `Dockerfile-prometheus`), `grafana`, `loki`. One `quake_platform` network. Named volumes: `pgdata`, `loki-data`, `grafana-data`, `vault-data`. Env-var-driven ports.
- `monitoring/prometheus.yml` — scrape configs: backend on `:8000/metrics`, celery-worker on `:8001/metrics`.
- `monitoring/loki-config.yml` — minimal Loki config (single-binary, filesystem storage).
- `monitoring/grafana/provisioning/datasources/datasources.yml` — Prometheus + Loki datasources.
- `monitoring/grafana/provisioning/dashboards/dashboards.yml` — dashboard provider pointing at `/var/lib/grafana/dashboards`.

**Acceptance**
- `docker compose config` passes (validates the file).
- `docker compose up -d` (run manually) brings every service to a Running state. `curl localhost:8000/health` returns ok. Grafana reachable on `:3000`. Vault sealed on `:8200`.

**Proposed commit message**
```
build: add docker-compose stack and monitoring configs (Prometheus, Loki, Grafana)
```

---

## Task 8 — Makefile

**Why now.** Everything the targets depend on now exists, so they all actually work.

**Files created**
- `makefile` — targets, grouped: **static analysis** (`check`, `format`, `find-unused`); **tests** (`test`, `test-report`, `coverage-badge`); **env/deps** (`install-env`, `install`, `install-test`, `install-dev`); **docker** (`build`, `up`, `down`, `restart`, `logs`, `status`, `clean`, `clean-logs`, `full-clean`, `prune`, `reset`); **vault** (`vault-status`, `vault-init`, `vault-unseal`, `vault-seal`); **db migrations** (`db-migrate`, `migrate-test`, `db-schema` — all stub-callable now; Epic 2 fills the `database/migrations/` content); **API keys** (`issue-api-key`, `revoke-api-key` — stub targets that `echo "not yet implemented (Epic 5)"`); **frontend** (`frontend-install`, `frontend-dev`, `frontend-build` — same stub pattern for Epic 7). Stubs are honest placeholders so the operator interface in `CLAUDE.md` matches reality.
- Always pass `--migrations-table public.schema_migrations` to dbmate in every target that invokes it.

**Acceptance**
- `make check` runs the full linter chain and passes on the current repo state.
- `make test` runs pytest and reports zero tests (no test files yet; that's expected — Epic 2 onward adds them).
- `make up` brings the stack up. `make down` tears it down.
- `make install-env` creates `.env` from `.env.template` on a fresh checkout.

**Proposed commit message**
```
chore: add makefile with full operator interface (lint, test, docker, vault, db, stubs)
```

---

## Task 9 — CI workflow

**Why last.** The CI runs `make check` + `make test`; both must work before we enforce them.

**Files created**
- `.github/workflows/code_quality_assurance.yml` — triggers: `push` to any branch + `pull_request`. Jobs:
  - `check`: `actions/setup-python@v5` with 3.14, cache pip, install dev+test requirements, run `make check`.
  - `test`: same setup, run `make test`. (No DB-dependent tests yet; once Epic 2 lands, this job will spin up TimescaleDB as a service container.)
- Status badge URL ready to drop into `README.md` (we'll wire that into the README in Epic 9 once there's something to be proud of, not now).

**Acceptance**
- Workflow YAML validates (`act` or GitHub's UI).
- A test push to a branch shows both jobs green.

**Proposed commit message**
```
ci: add static-analysis and test workflow (python 3.14)
```

---

## Open questions before we start Task 1

None that block kickoff. Two minor items I'll surface inline if they come up:
- The `pydantic-settings` import path / class style — Pydantic v2 idiom. Locking the major version in `requirements.txt` will set this.
- Whether `database/migrations/.gitkeep` should be replaced with a stub baseline migration here vs. in Epic 2. **Plan: defer to Epic 2.** Empty `.gitkeep` is fine for Epic 1.

---

## Workflow reminder

After each task: I run the linters (or `make check` from Task 8 onward) and `make test`, then stop with a summary and a proposed commit message. **I do not run `git add`, `git commit`, or `git push`.** You review the diff, commit, push, and prompt me for the next task.
