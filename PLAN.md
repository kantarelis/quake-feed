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
| 4 | Shared utilities (`functions/`) | ✅ Done | `eb540f7` |
| 5 | App entrypoints (`config.py`, `quake/main.py`, `quake/api/main/`, `__main__.py`) | ✅ Done | `eb2c9aa` |
| 6 | Dockerfile (single image for backend + worker + beat) | ✅ Done | `7e6bc52` |
| 7 | Docker Compose + monitoring configs | ✅ Done | `20f06af` |
| 8 | Makefile | ✅ Done | `da0e880` |
| 9 | CI workflow (`.github/workflows/code_quality_assurance.yml`) | ⬜ Not started | — |

**Status legend:** `⬜ Not started` · `🟡 In progress` · `✅ Done`
**Next:** Task 9.

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

## Task 4 — Shared utilities (`functions/`) ✅

**Status:** Done · Commit `eb540f7`

**Shipped**
- `functions/environment.py` — `Environment` `StrEnum`; eight typed config models (`BackendConfig`, `DatabaseConfig`, `LoggerConfig`, `PrometheusConfig`, `GrafanaConfig`, `RabbitMQConfig`, `VaultConfig`, top-level `EnvironmentalVariables`); explicit `_require()` / `_load_from_env()` env reader; `get_environmental_variables()` `lru_cache`'d accessor that calls `EnvironmentalVariables.model_validate(_load_from_env())`. `VaultConfig` exposes `address` and `unseal_keys_list` properties.
- `functions/logger.py` — `setup_logger(name, app_name, level)` returning a JSON-formatting stdout logger via `python-json-logger`'s `JsonFormatter(static_fields={"app": app_name})`. Idempotent via a `_quake_handler` marker attribute. Loki ship-side deferred to a promtail sidecar (Epic 8).
- `functions/vault.py` — `VaultClient` wraps `hvac` for the KV v2 mount `secret/` (`get_secret`, `put_secret`, `list_keys`; `InvalidPath` returns sane empties). `init_vault(logger)` builds the client and warns on uninitialized/sealed/unreachable Vault without raising — caller decides whether to fail fast.
- `functions/scheduler.py` — single helper `crontab_or_default(env_var, default) -> crontab` (5-field validation, defaults if env unset/empty).
- `functions/celery_metrics.py` — `CELERY_TASK_TOTAL` Counter + `CELERY_TASK_DURATION_SECONDS` Histogram + signal handlers on `task_prerun` / `task_postrun` / `task_failure`. Counter increments in `task_postrun` using `state` kwarg; `task_failure` is a documented no-op hook point for Epic 8.

**Plus config / docs changes that landed in the same commit:**
- `CLAUDE.md` — Static Analysis Gate section rewritten: the no-suppression rule is now absolute (no escape hatches), with the three permitted fix paths spelled out (refactor / project-wide config / plugin or stub).
- `setup.cfg` — added `plugins = pydantic.mypy` under `[mypy]` and a `[pydantic-mypy]` section (`init_forbid_extra = True`, `init_typed = True`, `warn_required_dynamic_aliases = True`).

**Verifications**
- All 5 linters pass across the whole repo (27 source files): isort exit 0, black 27 unchanged, flake8 exit 0, mypy 27 source files clean, bandit 0 issues at every severity.
- **Pyright also clean: 0 errors, 0 warnings, 0 informations** (run via `npx --yes pyright --pythonpath .venv/bin/python`).
- Plan's literal acceptance import line works: `from functions.environment import get_environmental_variables; from functions.logger import setup_logger; from functions.vault import VaultClient` (extended to all five modules; all succeed).
- `grep -rnE '# *(type: *ignore|noqa|nosec|pragma: *no *cover|mypy: *ignore|fmt: *(off|on))' …` returns empty across the source tree.

**Deviations from original plan**

1. **`environment.py` is `BaseModel`-based, not `pydantic-settings`-based.** The plan called for `EnvironmentalVariables(BaseSettings)` with nested `BaseSettings` groups via `Field(default_factory=…)`. That structure made pyright fail (9 errors) because pyright reads pydantic's native stubs (no plugin equivalent to mypy's `pydantic.mypy`), and the synthesized `__init__` requires all fields — so `BackendConfig()` (no args) is a static error. To satisfy the no-suppression rule, the module was restructured: sub-configs are plain `BaseModel`, and a single explicit `_load_from_env()` builds a nested dict that `EnvironmentalVariables.model_validate(...)` validates. Env-reading is now visible code, not magic. `.env` loading is the caller's job (Makefile sources it locally; docker-compose injects via `env_file:`). Same public API (`env.backend.host`, `env.database.port`, …).
2. **No in-process Loki HTTP handler.** Plan said "Loki handler when `LOKI_HOST` is reachable; otherwise stdout-only." Dropped the Loki HTTP path in favor of container-side log collection (the standard pattern: app logs JSON to stdout → promtail tails the docker log driver → ships to Loki). Cleaner, doesn't need a new dep. Promtail will be added to docker-compose in Epic 8.
3. **No suppressions anywhere** — the user instated an absolute no-line-level-suppression rule mid-task. CLAUDE.md was updated to reflect it (committed in this same Task 4 commit). All `# type: ignore` and `# noqa` directives previously added were removed and replaced with real fixes (pydantic plugin for mypy; restructure for pyright; specific exception tuple in `vault.py` replacing the broad `except Exception` + `# noqa: BLE001`).
4. **`pyright` is now part of the verification flow** (it wasn't in the original Task 4 acceptance). Currently invoked via `npx --yes pyright` for ad-hoc checks. It is **not yet wired into `make check` or CI** — open follow-up for Task 8 (Makefile) and Task 9 (CI) to lock it in as a hard gate.
5. **`pydantic-settings` is now unused.** Still pinned in `requirements.txt`. Can be removed; left for the user to decide whether to drop in this commit's follow-up or later.

---

## Task 5 — App entrypoints ✅

**Status:** Done · Commit `eb2c9aa`

**Shipped** — 6 new files
- `config.py` — `celery_app = Celery(_env.application_name, broker=BROKER_URL)`. `BROKER_URL` is composed from `RABBITMQ_*` env vars (`amqp://user:pass@host:port//` — double slash = default vhost). Conf: `timezone="UTC"`, `enable_utc=True`, `task_acks_late=True`, `worker_prefetch_multiplier=1`, `beat_schedule={}`. No signal handlers / no task registration (deferred to Epic 3).
- `quake/api/main/models.py` — `HealthResponse(status: str, service: str, version: str)`.
- `quake/api/main/views.py` — `MainManagerViews.__init__(logger)` + `async health() -> HealthResponse` returning `HealthResponse(status="ok", service=__title__, version=__version__)`. Pulls identity from `__metadata__` rather than hard-coding the string.
- `quake/api/main/main.py` — `MainManager(logger=None)` (defaults to `logging.getLogger("MainManager")` per the `CLAUDE.md` pattern). Owns `APIRouter()`, instantiates `MainManagerViews`, and `run()` wires `/health` via `add_api_route` (full OpenAPI metadata: summary, description, operation_id, tags) before returning the router.
- `quake/main.py` — `Quake(logger)` builds `FastAPI(title=__title__, description=__description__, version=__version__)`, calls `_mount_routers()` which constructs `MainManager` and `include_router(main_manager.run())`. `run(host, port)` logs an "Starting quake-feed" line with structured extras and calls `uvicorn.run(self.app, host=host, port=port)`.
- `__main__.py` — `main()` calls `get_environmental_variables()` → `setup_logger(name, app_name, level)` → `init_vault(logger)` (fire-and-forget; the client return is discarded, the warning side-effects are what matter at boot) → `Quake(logger).run(host, port)`. Guarded by `if __name__ == "__main__": main()`.

**Verifications**
- All 5 linters clean across 33 source files: isort exit 0 (3 files skipped — configs), black 33 unchanged, flake8 exit 0, mypy 33 source files / 0 issues, bandit 0 issues at every severity (398 LoC scanned).
- **Pyright clean**: 0 errors, 0 warnings, 0 informations.
- **No suppressions**: `grep -rnE '# *(type: *ignore|noqa|nosec|pragma: *no *cover|mypy: *ignore|fmt: *(off|on))'` across `.py` files (excluding `.venv` / `.mypy_cache`) returns empty.
- **Server boot**: `set -a; source .env; set +a; .venv/bin/python __main__.py` brought Uvicorn up on `0.0.0.0:8000`.
  - `curl localhost:8000/health` → `{"status":"ok","service":"quake-feed","version":"0.1.0"}` (HTTP 200).
  - `curl localhost:8000/docs` → HTTP 200 (auto-generated OpenAPI UI).
  - First two stdout lines are JSON, e.g. `{"timestamp":"…","level":"INFO","logger":"quake-feed-logger","message":"Starting quake-feed","app":"quake-feed","host":"0.0.0.0","port":8000}` — confirms the JSON formatter and the `app` static field are in effect.
  - `init_vault` emitted a single `WARNING` because the Vault container isn't running (no DNS for `vault:8200`) and continued without raising — the fail-soft contract from Task 4 works in the boot path.

**Deviations from original plan**
None of structural significance. One minor judgment call documented for posterity:

1. **`MainManager.__init__` accepts `Optional[logging.Logger]`** and falls back to `logging.getLogger("MainManager")`. The plan didn't pin the signature; I matched the `EventsManager` example in `CLAUDE.md` so future managers (Epic 2+) stay consistent. `Quake` always passes a real logger in, so the fallback is only ever used in standalone unit tests of the manager.
2. **Identity strings in `health()` come from `__metadata__`** (`__title__`, `__version__`) rather than the literal `"quake-feed"` string the plan showed. Single source of truth — bumping `__version__` is reflected in `/health` automatically.

**Open follow-ups (unchanged from Task 4 — not introduced here)**
- `pyright` is still run ad-hoc via `npx`; locking it into `make check` / CI is slated for Tasks 8 and 9.
- `pydantic-settings` is still pinned in `requirements.txt` despite being unused after the Task 4 refactor.

**Proposed commit message**
```
feat: add FastAPI entrypoint with /health and Manager/Views scaffold
```

---

## Task 6 — Dockerfile ✅

**Status:** Done · Commits `7e6bc52..eb901db`

**Shipped** — 2 new files
- `Dockerfile` — single-stage image from `python:3.14-slim`. Layer order: ENV (`PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`, `PIP_NO_CACHE_DIR=1`, `PIP_DISABLE_PIP_VERSION_CHECK=1`) → `apt-get install build-essential libpq-dev` + cleanup → `WORKDIR /app` → copy the three requirement files only → `pip install -r requirements-dev.txt` (pulls runtime + test + dev via the cascading `-r` chain) → copy full source → `groupadd appuser` + `useradd` (system, gid `appuser`, home `/app`) + `chown -R` → `USER appuser` → `CMD ["python", "__main__.py"]`. The split between requirements copy and source copy keeps the dependency layer cacheable across source-only rebuilds. Worker and beat services will override the command in `docker-compose.yml` (Task 7).
- `.dockerignore` — not in the task's listed deliverables but added as a judgment call (without it the build context would have shipped `.venv/`, `.git/`, and every cache directory). Excludes: VCS (`.git/`, `.gitignore`, `.gitattributes`), Python (`__pycache__/`, `*.py[cod]`, `.venv/`, `build/`, `dist/`, `*.egg-info/`), test/coverage/type-checker caches (`.pytest_cache/`, `.mypy_cache/`, `.coverage*`, `htmlcov/`, `.ruff_cache/`, etc.), `frontend/` + `node_modules/` (backend image needs neither), env/secret files (`.env`, `.env.local`, `.env.*.local`, `vault_init_output.txt`), generated `database/schema.sql`, Docker/Compose definitions themselves (`Dockerfile`, `.dockerignore`, `docker-compose.yml`, `docker-compose.override.yml`), `monitoring/` (mounted into Prometheus/Grafana/Loki via Compose volumes — not part of the app image), planning docs (`PLAN.md`, `MASTER_PLAN.md`, `docs/`), editor/OS noise, `*.log`.

**Verifications**
- `docker build -t quake-feed .` succeeded end-to-end on Docker 29.4.3. The install log shows `psycopg-binary-3.3.4` was installed as a precompiled wheel for `cp314`, so the C compiler never actually had to build psycopg from source.
- **Image size:** 677 MB (`docker images quake-feed`). Above the plan's "under ~600 MB" soft target by ~13%. See deviations.
- **Import smoke test (literal acceptance line, expanded):**
  `docker run --rm --entrypoint python quake-feed -c "import quake; import quake.api.main.main; import functions; import functions.environment; import functions.logger; import functions.vault; print('OK')"`
  → prints `OK`, exits 0. The image is importable; no Uvicorn boot because env vars aren't injected — matches the plan's expectation.

**Deviations from original plan**

1. **Image is 677 MB rather than under 600 MB.** Two contributors:
   - `build-essential` (~300 MB) is retained at runtime per the plan's explicit "system deps for `psycopg` (`libpq-dev`, `build-essential`)" wording. In practice psycopg installed from a wheel, so build-essential was only needed transiently. Reclaiming that space cleanly is a one-line addition to the same `RUN` layer: `&& apt-get purge -y build-essential && apt-get autoremove -y`. Flagged as a follow-up rather than acted on, because the plan explicitly listed those packages and the runtime change would be a structural deviation.
   - The full dev/test/lint stack is included on purpose (per the plan: keep `make test` runnable in-container without juggling images).

2. **`.dockerignore` added.** Not in the task's file list but necessary to make the build sane (without it `.venv/` and `.git/` would be in the context). Documented in the **Shipped** section above.

**Open follow-ups**
- (Unchanged from Task 4) `pyright` not yet wired into `make check` / CI — slated for Tasks 8 and 9.
- (Unchanged from Task 4) `pydantic-settings` still pinned in `requirements.txt` despite being unused after the Task 4 refactor.
- (New, Task 6) Decide whether to purge `build-essential` after install to reclaim ~300 MB. Cosmetic optimization; can be folded into a later pass or rolled into Task 7's compose-time validation.

**Proposed commit message**
```
build: add Dockerfile (single image for backend, worker, beat)
```

---

## Task 7 — Docker Compose + monitoring configs ✅

**Status:** Done · Commit `20f06af`

**Shipped** — 5 new files
- `docker-compose.yml` — 9 services on a single `quake_platform` bridge network (declared with `name: quake_platform` so the network isn't compose-project-prefixed). No top-level `version:` key (deprecated under Compose v2).
  - **App services** (all use the same image): `backend` is the only one with `build: .` + `image: quake-feed:latest`; `celery_worker` (`celery -A config.celery_app worker --loglevel=info`) and `celery_beat` (`celery -A config.celery_app beat --loglevel=info`) reference the same image. All three load app env via `env_file: .env`. `backend` publishes `${QUAKE_BIND_PORT}:${QUAKE_BIND_PORT}` (env-driven on both sides so changing the env var moves both host and container ports together).
  - **Stateful services**: `postgres-db` (`timescale/timescaledb:latest-pg18`, `POSTGRES_USER/PASSWORD/DB` mapped from `DB_*` env), `rabbitmq` (`rabbitmq:3-management`, `RABBITMQ_DEFAULT_USER/PASS` mapped, both AMQP and management ports published), `vault` (`hashicorp/vault:1.21.1`, `command: server -dev`, `cap_add: IPC_LOCK`, `VAULT_DEV_LISTEN_ADDRESS=0.0.0.0:8200`).
  - **Observability**: `prom/prometheus:v2.46.0` mounts `./monitoring/prometheus.yml`; `grafana/loki:3.2.0` mounts `./monitoring/loki-config.yml` + `loki-data` volume; `grafana/grafana:11.3.0` mounts the full provisioning tree (`./monitoring/grafana/provisioning` → `/etc/grafana/provisioning`) plus `./monitoring/grafana/dashboards` → `/var/lib/grafana/dashboards` and `grafana-data` volume.
  - **Named volumes**: `pgdata`, `loki-data`, `grafana-data`, `vault-data`.
  - **depends_on**: `backend` → postgres-db, rabbitmq, vault; `celery_worker` → rabbitmq, postgres-db; `celery_beat` → rabbitmq; `grafana` → prometheus, loki. Plain start-order dependencies (not `condition: service_healthy`) per the plan's lack of healthchecks.

- `monitoring/prometheus.yml` — `global` block (15 s scrape + evaluation intervals). Two static `scrape_configs`: `backend` (`backend:8000`, `/metrics`) and `celery_worker` (`celery_worker:8001`, `/metrics`).
- `monitoring/loki-config.yml` — single-binary Loki: `auth_enabled: false`, HTTP `:3100` / gRPC `:9096`, filesystem storage under `/loki`, in-memory ring, tsdb v13 schema starting `2024-01-01`, `analytics.reporting_enabled: false`.
- `monitoring/grafana/provisioning/datasources/datasources.yml` — Prometheus (default, `http://prometheus:9090`) + Loki (`http://loki:3100`). Both `editable: false`.
- `monitoring/grafana/provisioning/dashboards/dashboards.yml` — one file-based provider scanning `/var/lib/grafana/dashboards`, `updateIntervalSeconds: 10`.

**Verifications**
- `docker compose config` — exits 0, full rendered YAML valid.
- `docker compose config --services` lists all 9 expected services (`backend`, `celery_worker`, `celery_beat`, `postgres-db`, `rabbitmq`, `vault`, `prometheus`, `grafana`, `loki`).
- `docker compose config --volumes` lists exactly `pgdata`, `loki-data`, `grafana-data`, `vault-data`.
- `docker compose config --networks` lists exactly `quake_platform`.
- Variable substitution from `.env` resolved correctly in the rendered output (`VAULT_DEV_ROOT_TOKEN_ID: root-token`, `RABBITMQ_DEFAULT_USER: guest`, `POSTGRES_USER: quake`, etc.).
- `docker compose up -d` deliberately **not** run by Claude — the plan says "(run manually)". That step (and curling `/health`, hitting Grafana at `:3000`, etc.) is the user's verification.

**Deviations from original plan**

1. **Service named `postgres-db`, not `postgres`.** The shipped `.env.template` (Task 1) declares `DB_HOST="postgres-db"`. Matching the service name keeps Docker DNS resolution working without editing the env file. Cosmetic naming only — connection semantics unchanged.

2. **Loki and Grafana images pinned to specific versions** (`grafana/loki:3.2.0`, `grafana/grafana:11.3.0`). The plan listed them by image name only, with no tag. Pinned to recent-stable tags so the stack is reproducible across runs, mirroring the explicit pins the plan gave for Prometheus and Vault.

3. **`backend` publishes `${QUAKE_BIND_PORT}:${QUAKE_BIND_PORT}`** rather than hardcoding `8000` on the container side. Lets `QUAKE_BIND_PORT` flow end-to-end via env alone.

4. **No live-reload volumes mount on `backend`.** Plan said "optionally mounts the source via a `volumes:` entry for live-reload". Skipped: without `uvicorn --reload` the mount accomplishes nothing, and the runtime command is `python __main__.py`. Live-reload, if wanted, belongs in `docker-compose.override.yml` (already in `.gitignore`) to keep dev-only state out of the committed stack.

5. **Existing `.gitkeep` files under `monitoring/grafana/`** (`dashboards/`, `provisioning/datasources/`, `provisioning/dashboards/`) left in place. They're inert for Grafana (it only loads YAML/JSON), and removing them is a sweep not in this task's scope.

**Things to know before `docker compose up -d`**
- Prometheus scrape targets (`backend:8000/metrics`, `celery_worker:8001/metrics`) will show **DOWN** in Grafana — the `/metrics` endpoints aren't exposed yet (they land in later epics). Stack still comes up cleanly; this is cosmetic noise.
- Vault dev mode auto-unseals on startup; the plan's "Vault sealed on :8200" is read as "Vault reachable on :8200" (the dev-mode choice is explicit in the plan and `.env.template`). The unseal key is printed to the container logs; production-mode seal/unseal exercise will happen via `make vault-init` once Task 8 lands and (eventually) if the container mode changes.
- Backend's `init_vault` will now succeed (DNS resolves `vault` inside the network), upgrading the Task 5 boot-time WARNING to an INFO line.

**Open follow-ups**
- (Carry-over) `pyright` not yet wired into `make check` / CI — Tasks 8 and 9.
- (Carry-over) `pydantic-settings` still pinned in `requirements.txt` but unused.
- (Carry-over) Decide whether to purge `build-essential` from the Docker image to reclaim ~300 MB.

**Proposed commit message**
```
build: add docker-compose stack and monitoring configs (Prometheus, Loki, Grafana)
```

---

## Task 8 — Makefile ✅

**Status:** Done · Commit `da0e880`

**Shipped** — 1 new file
- `makefile` (lowercase, matching `CLAUDE.md` and the plan) — 36 targets organized into 9 groups, with `help` as the `.DEFAULT_GOAL`. Tool paths resolved through `$(VENV)/bin/<tool>` (default `VENV ?= .venv`) so the active interpreter is unambiguous. `$(DBMATE_FLAGS) = --migrations-table public.schema_migrations` is passed to every dbmate invocation per the plan and `CLAUDE.md`.
  - **Static analysis** — `check` runs **six** linters in sequence: isort, black, flake8, mypy, bandit, **pyright** (`npx --yes pyright --pythonpath .venv/bin/python`). `format` runs isort + black write-mode. `find-unused` runs vulture (config in `pyproject.toml`).
  - **Tests** — `test` runs pytest with an exit-code wrapper that converts pytest's exit-5 ("no tests collected") into success (`exit 0`) while preserving all other exit codes (1/2/3/4 still propagate). `test-report` runs pytest with `--cov=. --cov-report=html`. `coverage-badge` produces `coverage.svg`.
  - **Env / deps** — `install-env` copies `.env.template` → `.env` if missing, never overwrites. `install`, `install-test`, `install-dev` map 1:1 to the three requirements files.
  - **Docker / Compose** — `build`, `up` (depends on `install-env` so a fresh checkout self-bootstraps), `down`, `restart`, `logs`, `status`, `clean`, `clean-logs` (best-effort truncate with optional `sudo` fallback), `full-clean` (down + remove named volumes), `prune` (`docker system prune -f`, no `--volumes`), `reset` (full-clean → build → up).
  - **Vault** — `vault-status` (`vault status`, exit code swallowed because sealed is non-zero), `vault-init` (writes `vault_init_output.txt`), `vault-unseal` (loads `.env`, iterates the comma-separated `VAULT_UNSEAL_KEYS`), `vault-seal` (uses `VAULT_TOKEN` from `.env`). A comment block above the section flags that all four are no-ops while Vault runs in `-dev` mode.
  - **DB migrations** — `db-migrate` and `db-schema` invoke real dbmate against a `DATABASE_URL` composed inline from `.env` (`postgres://$DB_USERNAME:$DB_PASSWORD@localhost:$DB_PORT/$DB_NAME?sslmode=disable`); both gracefully no-op when `database/migrations/` is empty. `migrate-test` is an honest `echo "not yet implemented (Epic 2)"` stub.
  - **API keys** — `issue-api-key`, `revoke-api-key` — both `echo "not yet implemented (Epic 5)"`.
  - **Frontend** — `frontend-install`, `frontend-dev`, `frontend-build` — all `echo "not yet implemented (Epic 7)"`.

**Verifications**
- `make help` — prints all 34 user-facing targets with descriptions. Exit 0.
- `make check` — all six linters pass (isort 0, black 0, flake8 0, mypy 0 / 33 source files, bandit 0 issues / 398 LoC, pyright 0 errors / 0 warnings / 0 informations). Exit 0.
- `make test` — pytest reports `no tests ran`; wrapper prints `[make test] no tests collected (expected until Epic 2)` and exits 0.
- `make install-env` — verified **both** paths:
  - With `.env` present → prints `.env already exists; not overwriting.`, exits 0, leaves file untouched.
  - With `.env` removed (then restored from backup after) → prints `Created .env from .env.template.`, exits 0, file recreated at 2718 bytes.
- `make up` / `make down` deliberately not run by Claude — they wrap `docker compose up -d` / `down`, which was already validated in Task 7's `docker compose config` step.

**Deviations from original plan**

1. **`pyright` is now part of `make check`.** Resolves the carry-over follow-up from Task 4. Requires Node/npm on the host (the user already had it for the ad-hoc runs done in prior tasks). Task 9's CI workflow will need to install Node alongside Python. Adds ~3 s to a warm `make check` (npx caches pyright after first run).

2. **`make test` swallows pytest exit code 5.** Without the wrapper, `make test` would always fail on the current empty-suite state, which contradicts the plan's "passes on the current repo state" wording. The wrapper preserves every other pytest exit code intact.

3. **`clean-logs` does best-effort sudo fallback.** Docker log files are root-owned; the target tries `: > path` first, falls back to `sudo truncate -s 0 path`, and tolerates per-container failures. Prints `Container log files truncated where permissions allowed.` so the operator knows it was best-effort.

4. **`prune` is global (`docker system prune -f`)** rather than project-scoped, and **does not include `--volumes`** so it can't destroy named volumes by accident. `full-clean` is the only target that removes volumes.

5. **Vault targets ship even though Vault runs in `-dev` mode** (auto-init, auto-unseal). They'd error out today if invoked — that's intentional honest behavior, and the operator interface stays stable for the eventual production-mode flip.

6. **`up` depends on `install-env`** so a fresh-clone workflow is `git clone … && make up` — no manual `cp .env.template .env` step needed. Plan didn't pin the dependency relationship; this is a DX call.

**Follow-ups**

- **Resolved this task:** `pyright` is wired into `make check`. Consequence carried into Task 9: the CI workflow needs to install Node alongside Python.
- **(Carry-over)** `pydantic-settings` still pinned in `requirements.txt` but unused after the Task 4 refactor.
- **(Carry-over)** Decide whether to purge `build-essential` from the Docker image to reclaim ~300 MB.

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
