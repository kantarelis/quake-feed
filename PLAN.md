# PLAN.md — Epic 8: Observability (Prometheus metrics + Grafana dashboard)

**Status:** 🟡 In progress — Tasks 1–5 done (`9147ecd`, `fce892e`, `96b439d`, `dcf6f6c`, `f11626d`); Task 6 (docs) pending
**Epic source:** [`MASTER_PLAN.md`](MASTER_PLAN.md) — Epic 8
**Branch:** new feature branch off `kantarelis` (PRs target `kantarelis`)

---

## Goal

Make the running stack observable end-to-end: the backend and worker expose
Prometheus metrics, Prometheus scrapes both, and a **checked-in, provisioned
Grafana dashboard** shows ingestion health and live-stream activity at a glance.

Concretely:

- **App metrics** for the things that can silently break: ingestion success/
  latency/volume (`usgs_poll_seconds`, `usgs_poll_errors_total`,
  `events_inserted_total`, `events_updated_total`, `events_revisions_total`) and
  live-stream load (`sse_connections_active`).
- **Working exposition on both processes.** The API serves `/metrics` on `:8000`
  (already wired); the **Celery worker** gets a metrics endpoint on `:8001`
  (currently a dead scrape target).
- **A provisioned dashboard** — `monitoring/grafana/dashboards/ingestion.json` —
  auto-loaded by the existing Grafana provisioning, with a **Loki logs panel** so
  metrics and structured logs sit on one screen.
- **`docs/observability.md`** explaining the two-target model, the metric
  catalogue, and the worker-pool decision.

## Current state (what already exists — do not rebuild)

- `quake/api/main/views.py::metrics` serves `generate_latest()` at `/metrics`
  (`:8000`). `quake/api/main/__init__` imports `functions.celery_metrics` so the
  API registry isn't empty.
- `functions/celery_metrics.py` defines `celery_task_total` +
  `celery_task_duration_seconds` and connects `task_prerun/postrun/failure`.
- `monitoring/prometheus.yml` already scrapes **both** `backend:8000` and
  `celery_worker:8001`.
- Grafana provisioning is in place: `provisioning/datasources/datasources.yml`
  (Prometheus + Loki datasources) and `provisioning/dashboards/dashboards.yml`
  (file provider pointing at `/var/lib/grafana/dashboards`, mounted from
  `monitoring/grafana/dashboards/` in `docker-compose.yml`).
- `functions/logger.py` already ships structured logs to Loki.

## The core problem this epic must solve (drives Task 1)

`prometheus_client` metrics live in a **per-process** registry. Two consequences:

1. **The worker has no metrics endpoint.** Prometheus scrapes `celery_worker:8001`
   but nothing listens there → the target is permanently DOWN, and the existing
   `celery_task_*` counters are exposed nowhere.
2. **Prefork scatters metrics across child processes.** Celery's default `prefork`
   pool runs tasks in forked **child** processes. `task_*` signals and any
   ingestion-metric increments fire in the child, while a metrics HTTP server
   started at worker boot lives in the **main** process — so it would expose an
   empty registry.

Both must be fixed before any worker-side metric is meaningful. See design
choice 2.

## Design choices (locked up-front so tasks don't re-litigate)

1. **Two scrape targets, per-process registries — no cross-process aggregation.**
   API metrics on `:8000/metrics` (FastAPI, single uvicorn process); worker
   metrics on `:8001/metrics` (`prometheus_client.start_http_server`). Prometheus
   already targets both; dashboard queries `sum()` across `instance`/`job` so a
   metric that only one process emits (e.g. `sse_connections_active` on the API,
   ingestion counters on the worker) aggregates cleanly.

2. **Worker runs a single-OS-process pool (`--pool=threads`) so its registry is
   shared.** This is the simplest correct fix to the prefork problem: with a
   threads pool there is one process, task execution and the metrics HTTP server
   share one registry, and the ingestion workload is I/O-bound (USGS fetch + DB
   writes — GIL released during I/O) so threads are a fine fit at this scale.
   *Rejected alternative:* `prometheus_client` multiprocess mode
   (`PROMETHEUS_MULTIPROC_DIR` + `MultiProcessCollector`) — the "correct at scale"
   answer, but heavier (shared dir lifecycle, gauge modes, per-child files) and
   unjustified for a local-only, single-pod, one-task-per-minute worker. Noted as
   the migration path if real task parallelism is ever needed.

3. **Metrics-server bootstrap is scoped to the worker via Celery's `worker_init`
   signal.** The handler that calls `start_http_server(port)` connects to
   `worker_init` (fires once, in the worker main process). The API process imports
   the metric *definitions* but never fires `worker_init`, so it never tries to
   bind `:8001` — no port clash, no conditional `if process == ...` branching.

4. **App/domain metrics live in a new `functions/metrics.py`**, parallel to
   `functions/celery_metrics.py`. Module-level metric objects on the default
   registry; importing the module is the only registration step (same pattern as
   `celery_metrics`).

5. **Metric catalogue (names + types) is fixed here:**
   | Metric | Type | Labels | Where incremented |
   |--------|------|--------|-------------------|
   | `usgs_poll_seconds` | Histogram | — | `poll_once` (worker) |
   | `usgs_poll_errors_total` | Counter | — | `poll_once` except path (worker) |
   | `events_inserted_total` | Counter | — | `poll_once` from `IngestionResult` (worker) |
   | `events_updated_total` | Counter | — | `poll_once` from `IngestionResult` (worker) |
   | `events_revisions_total` | Counter | — | `poll_once` from `IngestionResult` (worker) |
   | `sse_connections_active` | Gauge | — | `SubscriberRegistry` subscribe/unsubscribe (API) |

   No high-cardinality labels (no per-`event_id`). `events_revisions_total` is
   added beyond the MASTER_PLAN list because the count is already on hand and
   "USGS refined an estimate" is genuinely useful to chart.

6. **Worker metrics port is env-configured** (`WORKER_METRICS_PORT`, default
   `8001`), added to `.env.template` + `functions/environment.py` to match the
   repo's config-via-env discipline. The `8001` in `prometheus.yml` stays the
   source of truth for the scrape side.

7. **Dashboard is code.** `monitoring/grafana/dashboards/ingestion.json` is a
   committed dashboard JSON discovered by the existing file provider — no manual
   Grafana clicks, no DB-stored dashboards. Panels target the Prometheus
   datasource by name; one panel targets Loki.

8. **Loki: dashboard panel + a minimal collector.** *Corrected during Task 4:*
   the original assumption that "the logging→Loki pipeline already exists" was
   wrong — `functions/logger.py` only writes JSON to stdout and there is **no log
   collector** in `docker-compose.yml` (its docstring even defers this to "Epic 8").
   So the epic adds the logs panel (Task 4) **and** a minimal collector that ships
   container stdout to Loki under `job="quake-feed"` (Task 5), rather than leaving
   the panel permanently empty. The collector config itself is kept minimal — not
   a full logging re-architecture.

## Out of scope

- **Alerting / Alertmanager.** No alert rules, no notification routing — dashboards
  only.
- **Multiprocess-mode metrics** (design choice 2) and any worker concurrency
  beyond the threads pool.
- **Per-endpoint HTTP metrics / RED method on the API** (request latency
  histograms per route, `starlette-exporter`-style). Could be a later epic; this
  epic targets ingestion + stream health, the things unique to this service.
- **Recording rules / long-term storage / remote-write.** Default Prometheus
  local TSDB only.
- **Tracing** (OpenTelemetry / Tempo).
- **New backend features.** Metrics observe existing paths; no behavioural change
  to ingestion or the API beyond instrumentation + the worker pool flag.

---

## Tasks

Each task is **one commit**. Every task runs `make check` + `make test`. Tasks
touching `docker-compose.yml` / dashboard JSON also get a manual
bring-up-the-stack verification noted in their acceptance. Stop after each task;
wait for the user before starting the next.

| # | Task | Files (new unless noted) | Status |
|---|------|--------------------------|--------|
| 1 | Worker metrics exposition — `start_http_server(:8001)` via `worker_init` + threads pool, so the worker registry (celery + future ingestion metrics) is actually scraped | `functions/celery_metrics.py` (mod), `functions/environment.py` (mod), `.env.template` (mod), `docker-compose.yml` (mod), `config.py` (mod, +1 deviation), `tests/unit/test_celery_metrics.py` | ✅ `9147ecd` |
| 2 | App metrics module + ingestion instrumentation (`usgs_poll_seconds`, `usgs_poll_errors_total`, `events_{inserted,updated,revisions}_total`) wired into `poll_once` | `functions/metrics.py`, `quake/events/ingest.py` (mod), `tests/unit/test_metrics.py`, `tests/unit/test_ingest.py` (mod) | ✅ `fce892e` |
| 3 | `sse_connections_active` gauge wired into the subscriber registry, exposed on the API `/metrics` | `functions/metrics.py` (mod), `quake/alerts/registry.py` (mod), `tests/unit/test_subscriber_registry.py` (mod) | ✅ `96b439d` |
| 4 | Grafana ingestion-health dashboard (provisioned JSON) incl. a Loki logs panel | `monitoring/grafana/dashboards/ingestion.json`, `tests/unit/test_dashboard_provisioning.py`, `requirements-test.txt` (mod, +1 deviation) | ✅ `dcf6f6c` |
| 5 | Log collection → Loki: a minimal collector that ships container stdout to Loki under `job="quake-feed"` so Task 4's logs panel populates | `docker-compose.yml` (mod), `monitoring/promtail-config.yml` (new), `functions/logger.py` (docstring, mod), `tests/unit/test_log_collection.py` (new) | ✅ `f11626d` |
| 6 | `docs/observability.md` + env/makefile polish (`make metrics`, Grafana hint) | `docs/observability.md`, `makefile` (mod), `README.md` (mod, optional) | ⬜ |

---

### Task 1 — Worker metrics exposition + threads pool ✅ `9147ecd`

**Outcome.** Shipped as planned.

- `functions/celery_metrics.py` — added `_start_metrics_server`, connected via
  `@worker_init.connect` (matching the file's existing decorator-based signal
  pattern). It reads the port from config and calls
  `prometheus_client.start_http_server(port)` once in the worker main process.
  Module docstring updated to note the new `worker_init` hook and that the module
  must be imported in the worker boot path.
- `functions/environment.py` — added a small `WorkerConfig(metrics_port: int)`
  block (chosen over folding into `PrometheusConfig`, which models the Prometheus
  *server* host/port, not exposition). `WORKER_METRICS_PORT` is read in
  `_load_from_env` via `os.environ.get(..., "8001")` — **optional with a default**
  so the API and test envs need not set it (and the sandbox env helper needed no
  change).
- `.env.template` — added `WORKER_METRICS_PORT=8001` under a "Celery worker
  metrics" comment tying it to the `celery_worker:8001` scrape target.
- `docker-compose.yml` — `celery_worker` command gained `--pool=threads`;
  `celery_beat` left unchanged.
- `tests/unit/test_celery_metrics.py` — two tests, both mocking
  `start_http_server` (no real socket): handler binds the configured port (direct
  call), and `worker_init.send_robust(...)` triggers it (proves the signal wiring;
  `send_robust` isolates from unrelated receivers).

**Deviation (1, structural — flagged and approved at review).** Added
`config.py` to the touched files, outside the planned scope. `functions.celery_metrics`
was imported **only** by the API (`quake/api/main/__init__.py`); nothing in the
worker boot path imported it, so neither the new `worker_init` handler *nor the
existing `celery_task_*` handlers* would have registered in the worker — making
the acceptance ("`celery_task_total` appears on `celery_worker:8001`")
unreachable. Fixed with a side-effect import in `config.py` (the `-A` app module,
guaranteed loaded at worker boot), routed through `importlib.import_module(...)`
to stay lint-clean without suppressions — the same idiom `tests/unit/test_tasks.py`
already uses. No `ports:`/`expose:` was added: Prometheus reaches
`celery_worker:8001` over the compose network without host publishing.

**Verification.** `make check` clean (isort, black, flake8, mypy, bandit, pyright).
`make test` green — 208 unit + 4 integration. Manual `make up` / Prometheus
`/targets` check remains a user step.

**Commit message (as committed).**

```
feat(metrics): add Celery worker metrics exposure and configuration
```

---

### Task 2 — App metrics module + ingestion instrumentation ✅ `fce892e`

**Outcome.** Shipped as planned.

- `functions/metrics.py` — the catalogue metrics as module-level objects on the
  default registry (UPPER_SNAKE constants, matching `celery_metrics`):
  `USGS_POLL_SECONDS` (Histogram) + `USGS_POLL_ERRORS_TOTAL`,
  `EVENTS_INSERTED_TOTAL`, `EVENTS_UPDATED_TOTAL`, `EVENTS_REVISIONS_TOTAL`
  (Counters). Counters carry the `_total` suffix in their name — verified that
  `prometheus_client` then exposes the sample as exactly `events_inserted_total`
  (matching the catalogue and the existing `celery_task_total`).
- `quake/events/ingest.py::poll_once` — the inner fetch→parse→upsert→count block
  now runs inside `with USGS_POLL_SECONDS.time()`; the except path increments
  `USGS_POLL_ERRORS_TOTAL` then re-raises unchanged; the success path increments
  the three `events_*_total` counters from the `IngestionResult` counts. The
  lock-skip early return is untouched (increments nothing).
- `tests/unit/test_metrics.py` — asserts catalogue samples register on `REGISTRY`
  and the objects have the expected `Counter`/`Histogram` types.
- `tests/unit/test_ingest.py` — added a `_metric_snapshot()` helper (reads via
  `REGISTRY.get_sample_value`) and three **delta** tests: successful poll, error
  poll, lock-skip.

**Decision recorded (within scope, no deviation).** `USGS_POLL_SECONDS.time()`
observes on context-exit whether the block completes or raises, so a *failed*
poll is still timed (`usgs_poll_seconds_count` += 1 alongside the error counter);
the error test pins this. Consequence for Task 4: the `histogram_quantile` poll-
duration panel mixes success and failure latency — intended (a slow timeout is
worth seeing), but noted so the dashboard query/labelling reflects it.

**Verification.** `make check` clean (isort, black, flake8, mypy [100 files],
bandit, pyright). `make test` green — 213 unit (+5 new) + 4 integration.

**Commit message (as committed).**

```
feat(metrics): add Prometheus metrics for USGS polling and corresponding unit tests
```

---

### Task 3 — SSE connections gauge ✅ `96b439d`

**Outcome.** Shipped as planned.

- `functions/metrics.py` — added `SSE_CONNECTIONS_ACTIVE` (Gauge). Docstring
  updated to note the gauge is moved only in the API process and that the
  `sum()`-across-instances model still aggregates cleanly.
- `quake/alerts/registry.py` — `subscribe()` calls `.inc()` after adding the
  slot; `unsubscribe()` calls `.dec()` **inside the `if sub is not None` guard**
  so the idempotent no-op path doesn't drift the gauge (stays consistent with
  `len(self._subs)`).
- `tests/unit/test_subscriber_registry.py` — `_gauge()` reader + three **delta**
  tests: rises on subscribe / falls on unsubscribe, unchanged on unknown-id
  unsubscribe, nets to zero after a subscribe→unsubscribe cycle.

**Decision recorded (within scope).** Tests assert deltas, not absolutes: the
gauge is process-global while the suite spins up many `SubscriberRegistry()`
instances (some never unsubscribe), so absolute reads would be polluted. In
production there is a single registry, so the gauge equals `len(self._subs)` as
the spec requires. The integration `test_alerts_stream` (real subscribe/
unsubscribe path) passes unchanged, confirming the wiring doesn't disturb the
SSE lifecycle.

**Verification.** `make check` clean (isort, black, flake8, mypy [100 files],
bandit, pyright). `make test` green — 216 unit (+3 new) + 4 integration.

**Commit message (as committed).**

```
feat(metrics): implement SSE connections gauge and update related tests
```

---

### Task 4 — Grafana ingestion-health dashboard ✅ `dcf6f6c`

**Outcome.** Shipped as planned; surfaced a scope correction (see Task 5).

- `monitoring/grafana/dashboards/ingestion.json` (`uid: quake-ingestion`) — five
  panels, all `sum()`-aggregated across instances: **Poll rate & errors**, **Poll
  duration (p50/p95)** (`histogram_quantile` over `usgs_poll_seconds_bucket`),
  **Event ingest rate (inserted/updated/revisions)**, **Active SSE connections**
  (stat), **Application logs** (Loki, query `{job="quake-feed"} | json`).
  Datasources referenced by **name** (`"Prometheus"` / `"Loki"`) — Grafana 11
  resolves string names for provisioned datasources.
- `tests/unit/test_dashboard_provisioning.py` — three drift guards: JSON parses +
  has uid/panels; expected panel titles present; every panel- **and** target-level
  datasource name is declared in `datasources.yml`.

**Deviation (1, minor).** Added `requirements-test.txt` (declared `PyYAML==6.0.3`):
the drift test parses the datasource YAML, and PyYAML was only present transitively
(via bandit) — declared explicitly rather than hand-rolling a brittle regex.

**Scope correction raised here → new Task 5.** Design choice 8 had assumed "the
logging→Loki pipeline already exists." It didn't — `functions/logger.py` only writes
JSON to stdout and there was **no log collector** in `docker-compose.yml`. So the
Loki panel would render empty. Rather than ship a dead panel, a minimal collector
was added as **Task 5** (design choice 8 updated, docs task renumbered to Task 6).

**Verification.** `make check` clean (101 source files). `make test` green — 219
unit (+3 new) + 4 integration. Manual Grafana render remains a user step.

**Commit message (as committed).**

```
feat(observability): add Grafana ingestion dashboard and log collection tests
```

---

### Task 5 — Log collection → Loki ✅ `f11626d`

*Added during Task 4 review (design choice 8 correction): the Loki panel has no
data source until container logs actually reach Loki.*

**Outcome.** Shipped as planned (promtail + `docker_sd_configs`, both confirmed at
review).

- `docker-compose.yml` — added the `promtail` service (`grafana/promtail:3.2.0`,
  version-matched to Loki); mounts the config and the Docker socket **read-only**;
  `depends_on: loki`.
- `monitoring/promtail-config.yml` (new) — `docker_sd_configs` discovery; a `keep`
  relabel scopes collection to the three app services (`backend`, `celery_worker`,
  `celery_beat`) so infra containers are dropped and the stream stays JSON-only;
  stamps `job="quake-feed"` + `service`/`container` labels; pushes to `loki:3100`.
- `functions/logger.py` — docstring corrected to point at the promtail service.
- `tests/unit/test_log_collection.py` (new, optional per acceptance) — drift guard
  tying promtail's `job` label to the dashboard's Loki query (rename on either side
  fails CI), plus config-parses / pushes-to-loki checks.

**Decisions (confirmed at review).** promtail (not Grafana Alloy); `docker_sd_configs`
with the docker socket mounted **read-only** (not a static file tail). App-only
stream (the `keep` relabel) so `{job="quake-feed"} | json` always parses.

**Verification.** `make check` clean (102 source files). `make test` green — 222
unit (+3 new) + 4 integration. `docker compose config` validates the full stack
with promtail. Manual Grafana logs-panel render remains a user step.

**Commit message (as committed).**

```
feat(observability): add Promtail configuration and tests for log collection to Loki
```

---

### Task 6 — Docs + env/makefile polish

**Scope.**

- `docs/observability.md` — the two-target scrape model (API `:8000`, worker
  `:8001`), the worker threads-pool decision and why (prefork vs registry), the
  metric catalogue, how to reach Prometheus/Grafana locally, and a couple of Loki
  log queries. Linked from the README "Subsystems" table.
- `makefile` — a small convenience target (e.g. `metrics` to curl both `/metrics`
  endpoints, or a Grafana-URL echo); align with existing target style.
- `README.md` (optional) — add the observability doc to the subsystems table.

**Acceptance.** `make check` + `make test` clean (docs/makefile only — no Python
change). Manual: dead-link check on the new doc.

**Commit message (proposed).**

```
docs(observability): metric catalogue + scrape model + dashboard guide

docs/observability.md explains the two-target Prometheus model, the
worker threads-pool decision, the metric catalogue, and how to view
Grafana/Loki locally. Adds a make helper and links the doc from README.
```

---

## After all tasks ship

- User confirms commit range, then asks Claude to:
  - Mark Epic 8 ✅ Done in `MASTER_PLAN.md` with the commit range.
  - Archive this `PLAN.md` to `docs/history/epic-08-observability.md` (single rename commit).
- Root `PLAN.md` slot is then free for Epic 9 (Documentation polish).
