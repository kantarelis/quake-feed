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
| 1 | Root hygiene (`.gitignore`, `.env.template`, pre-commit) | ⬜ Not started | — |
| 2 | Python tooling config (`pyproject.toml`, `setup.cfg`, `pytest.ini`, `requirements*.txt`, `__metadata__.py`) | ⬜ Not started | — |
| 3 | Directory skeleton (empty `__init__.py` packages) | ⬜ Not started | — |
| 4 | Shared utilities (`functions/`) | ⬜ Not started | — |
| 5 | App entrypoints (`config.py`, `quake/main.py`, `quake/api/main/`, `__main__.py`) | ⬜ Not started | — |
| 6 | Dockerfiles (`Dockerfile`, `Dockerfile-dev`, `Dockerfile-prometheus`) | ⬜ Not started | — |
| 7 | Docker Compose + monitoring configs | ⬜ Not started | — |
| 8 | Makefile | ⬜ Not started | — |
| 9 | CI workflow (`.github/workflows/code_quality_assurance.yml`) | ⬜ Not started | — |

**Status legend:** `⬜ Not started` · `🟡 In progress` · `✅ Done`
**Next:** Task 1.

---

## Task 1 — Root hygiene

**Why first.** Without `.gitignore` the very first commit could capture `PLAN.md`, `.env`, `__pycache__/`, etc. Get the guard rails in before any other file.

**Files created**
- `.gitignore` — Python (`__pycache__`, `*.pyc`, `.venv`, `*.egg-info`, `dist`, `build`, `htmlcov`, `.coverage`, `.mypy_cache`, `.pytest_cache`), Node (`node_modules`, `frontend/dist`), tooling (`.idea`, `.vscode`), env/secrets (`.env`, `vault_init_output.txt`), generated artifacts (`database/schema.sql`), and **explicitly `PLAN.md`**.
- `.env.template` — every variable the stack will reference, with safe local defaults: `ENVIRONMENT`, `APPLICATION_NAME`, `QUAKE_HOST_IP`, `QUAKE_BIND_PORT`, `DB_USERNAME`/`DB_PASSWORD`/`DB_NAME`/`DB_HOST`/`DB_PORT`, `LOGGER_NAME`/`LOGGER_LOG_LEVEL`/`LOKI_HOST`/`LOKI_PORT`, `PROMETHEUS_HOST`/`PROMETHEUS_PORT`/`GRAFANA_HOST`/`GRAFANA_PORT`/`GF_SECURITY_ADMIN_USER`/`GF_SECURITY_ADMIN_PASSWORD`, `RABBITMQ_HOST`/`RABBITMQ_USERNAME`/`RABBITMQ_PASSWORD`/`RABBITMQ_AMQP_PORT`/`RABBITMQ_MANAGEMENT_PORT`, `VAULT_HOST`/`VAULT_PORT`/`VAULT_DEV_ROOT_TOKEN_ID`/`VAULT_UNSEAL_KEYS`/`VAULT_TOKEN`.
- `.pre-commit-config.yaml` — hooks for isort, black, flake8, mypy (light, no full type-check), bandit, plus `end-of-file-fixer`, `trailing-whitespace`, `check-yaml`, `check-toml`. Pinned versions matching what we'll install in Task 2.

**Acceptance**
- `git status` does **not** show `.env`, `PLAN.md`, `__pycache__/`, or `vault_init_output.txt` if those files exist locally.
- `pre-commit --version` works after `pip install pre-commit` (host-level).

**Proposed commit message**
```
chore: add repo hygiene (gitignore, env template, pre-commit config)
```

---

## Task 2 — Python tooling config

**Why now.** Land tooling before code so every later commit can be linted/typed without retroactive churn.

**Files created**
- `pyproject.toml` — `[tool.black]` (line-length 120, `target-version = ["py314"]`), `[tool.isort]` (black profile, line-length 120), `[tool.bandit]` (skips empty, excludes `.venv`, `tests`, `dist`, `frontend`), `[tool.vulture]` (paths `["."]`, ignore decorators for `@celery_app.task` / `@*.connect`), `[tool.pyright]` (optional, mirrors mypy).
- `setup.cfg` — `[isort]`, `[flake8]` (max-line-length 120, ignore `E203,W503` for black compatibility, exclude `.venv,frontend,dist,build`), `[mypy]` (`python_version = 3.14`, `strict_optional = True`, `disallow_untyped_defs = True`, ignore-missing-imports for known untyped libs).
- `pytest.ini` — testpaths `tests`, addopts `-ra --strict-markers`, `pythonpath = .`, markers section.
- `requirements.txt` — runtime deps pinned to known-good 3.14-compatible versions: `fastapi`, `uvicorn[standard]`, `sse-starlette`, `pydantic`, `pydantic-settings`, `psycopg[binary]`, `celery`, `kombu`, `hvac` (Vault), `prometheus-client`, `python-json-logger`, `httpx`, `tenacity`, `sentry-sdk` (optional).
- `requirements-dev.txt` — `isort`, `black`, `flake8`, `mypy`, `bandit`, `vulture`, `pre-commit`, `ipython`.
- `requirements-test.txt` — `pytest`, `pytest-asyncio`, `pytest-cov`, `coverage-badge`, `httpx` (already in runtime but pinning is fine), `pytest-postgresql` (if we end up wanting it; can defer).
- `__metadata__.py` — `__version__ = "0.1.0"`, `__author__`, `__license__ = "MIT"`. No personal-identifying details inside the repo file.

**Acceptance**
- `pip install -r requirements.txt -r requirements-dev.txt -r requirements-test.txt` succeeds in a fresh venv.
- `isort --check .`, `black --check .`, `flake8 .`, `mypy .`, `bandit -r -c pyproject.toml .` all pass on the empty-ish repo.

**Proposed commit message**
```
chore: add python tooling config and pinned requirements (3.14)
```

---

## Task 3 — Directory skeleton

**Why now.** Establishing the import surface up front means every later task adds *content* to known files, not new directories.

**Files created** (all empty `__init__.py` unless noted)
- `quake/__init__.py`, `quake/api/__init__.py`, `quake/api/main/__init__.py`, `quake/api/events/__init__.py`, `quake/api/alerts/__init__.py`, `quake/api/ingest/__init__.py`, `quake/api/locks/__init__.py`
- `quake/ingestion/__init__.py`, `quake/ingestion/usgs/__init__.py`
- `quake/events/__init__.py`, `quake/alerts/__init__.py`
- `database/__init__.py`, `database/etls/__init__.py`, `database/migrations/.gitkeep`
- `functions/__init__.py`
- `models/__init__.py`
- `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/manual/__init__.py`, `tests/fixtures/__init__.py`, `tests/conftest.py` (empty)
- `docs/.gitkeep`
- `monitoring/grafana/dashboards/.gitkeep`, `monitoring/grafana/provisioning/datasources/.gitkeep`, `monitoring/grafana/provisioning/dashboards/.gitkeep`
- `frontend/.gitkeep` (frontend scaffold is its own epic)

**Acceptance**
- `python -c "import quake; import functions; import models; import database"` succeeds.
- Linters still pass.

**Proposed commit message**
```
chore: scaffold package directory layout
```

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
- `config.py` — top-level Celery app instance (`celery_app = Celery(...)`); empty `beat_schedule` placeholder; broker URL composed from env. Beat-init/worker-init signal handlers (Sentry init stub, deferred publisher seeding stub) that are no-ops for now but match the shape we'll need.
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
