# Observability — metrics, dashboard & logs

The running stack is observable end-to-end: the API and the Celery worker each
expose Prometheus metrics, Prometheus scrapes both, a checked-in Grafana
dashboard charts ingestion health and live-stream load, and promtail ships the
app's structured logs to Loki so logs and metrics sit on one screen.

This document covers (a) the two-target scrape model and why the worker runs a
threads pool, (b) the metric catalogue, (c) the provisioned dashboard, (d) the
log pipeline, and (e) how to reach it all locally.

## Two scrape targets, per-process registries

`prometheus_client` metrics live in a **per-process** registry, and this service
runs metrics in two different processes:

```
 ┌─────────────────────────┐        ┌──────────────────────────────┐
 │  API (uvicorn, 1 proc)  │        │  Celery worker (threads pool) │
 │  GET /metrics  :8000     │        │  start_http_server :8001      │
 │  • sse_connections_active│        │  • usgs_poll_seconds          │
 │  • (defs for the rest)   │        │  • usgs_poll_errors_total     │
 │                          │        │  • events_{ins,upd,rev}_total │
 │                          │        │  • celery_task_*              │
 └────────────┬─────────────┘        └───────────────┬──────────────┘
              │                                       │
              └──────────────┐         ┌──────────────┘
                             ▼         ▼
                      ┌──────────────────────┐
                      │      Prometheus       │  scrapes backend:8000
                      │      :9090            │  and celery_worker:8001
                      └──────────────────────┘
```

Both processes import `functions/metrics.py`, so **every metric is *defined* in
both registries** — but each metric is only ever *moved* by one process (the
worker increments the ingestion counters; the API moves the SSE gauge). Dashboard
queries therefore `sum()` across the `instance`/`job` label so a metric aggregates
cleanly no matter which process emits it. The process that never touches a given
metric just reports `0`.

- **API** — `quake/api/main/views.py::metrics` serves `generate_latest()` at
  `/metrics` on the uvicorn port (`:8000`). Single process, so no aggregation
  needed on this side.
- **Worker** — `functions/celery_metrics.py` connects a `worker_init` handler that
  calls `prometheus_client.start_http_server(WORKER_METRICS_PORT)` (default
  `8001`). The API imports the same module for the metric *definitions* but never
  emits `worker_init`, so it never binds `:8001`.

`monitoring/prometheus.yml` scrapes both targets; `8001` there is the source of
truth for the scrape side, and `WORKER_METRICS_PORT` configures the bind side.

### Why the worker runs `--pool=threads`

Celery's default **prefork** pool runs each task in a forked **child** process.
Task signals and ingestion-metric increments would fire in the child, while the
metrics HTTP server started at `worker_init` lives in the **main** process — so
`:8001` would expose an empty registry.

The worker therefore runs `--pool=threads` (`docker-compose.yml`): one OS process,
so task execution and the HTTP exporter share one registry. The ingestion
workload is I/O-bound (USGS fetch + DB writes, GIL released during I/O), so threads
are a fine fit at this scale. `celery_beat` is left on its default pool — it runs
no tasks.

*Rejected:* `prometheus_client` multiprocess mode (`PROMETHEUS_MULTIPROC_DIR` +
`MultiProcessCollector`) — correct at scale, but heavier (shared-dir lifecycle,
gauge modes, per-child files) and unjustified for a local-only, single-pod,
one-poll-per-minute worker. It's the migration path if real task parallelism is
ever needed.

## Metric catalogue

All single-value, no high-cardinality labels (no per-`event_id`).

| Metric | Type | Where it moves | Meaning |
|--------|------|----------------|---------|
| `usgs_poll_seconds` | Histogram | worker (`poll_once`) | Duration of one fetch→parse→upsert cycle. Observed on **both** success and failure, so a failed poll is timed too. |
| `usgs_poll_errors_total` | Counter | worker (`poll_once` except path) | Poll cycles that raised before completing. |
| `events_inserted_total` | Counter | worker (`poll_once`) | Events inserted, summed across polls. |
| `events_updated_total` | Counter | worker (`poll_once`) | Events updated, summed across polls. |
| `events_revisions_total` | Counter | worker (`poll_once`) | Revisions written by the DB trigger, summed across polls. |
| `sse_connections_active` | Gauge | API (subscriber registry) | Currently-connected SSE alert subscribers. |
| `celery_task_total` | Counter | worker | Celery tasks executed, by `task_name` + `status`. |
| `celery_task_duration_seconds` | Histogram | worker | Celery task execution time, by `task_name`. |

The ingestion metrics are defined in `functions/metrics.py`; the Celery task
metrics in `functions/celery_metrics.py`.

## The dashboard

`monitoring/grafana/dashboards/ingestion.json` (uid `quake-ingestion`, title
*Quake-feed — Ingestion & Stream Health*) is **provisioned**: the file provider in
`monitoring/grafana/provisioning/dashboards/dashboards.yml` auto-loads it from
`/var/lib/grafana/dashboards`. No manual Grafana clicks; no DB-stored dashboards.
Panels reference the provisioned datasources by name (`Prometheus`, `Loki`).

Panels (all `sum()`-aggregated across instances):

1. **Poll rate & errors** — poll cadence (`celery_task_total` for `poll_usgs`) vs
   `rate(usgs_poll_errors_total[5m])`.
2. **Poll duration (p50 / p95)** — `histogram_quantile` over
   `usgs_poll_seconds_bucket`. (Mixes success and failure latency — failures are
   timed too; a slow timeout is worth seeing.)
3. **Event ingest rate** — inserted / updated / revisions per second.
4. **Active SSE connections** — `sse_connections_active`.
5. **Application logs** — a Loki panel (see below).

`tests/unit/test_dashboard_provisioning.py` guards the JSON against drift: it must
parse, carry the expected panels, and only reference datasources declared in
`datasources.yml`.

## Logs → Loki

`functions/logger.py` emits structured JSON to stdout; collection happens at the
container layer. A **promtail** service (`docker-compose.yml` +
`monitoring/promtail-config.yml`) discovers containers via the Docker API
(`docker_sd_configs`, socket mounted read-only), keeps only the three app services
(`backend`, `celery_worker`, `celery_beat`), and pushes their logs to Loki under
the stream label `job="quake-feed"`. Infra containers (db, rabbitmq, …) are
dropped so the stream stays JSON-only and `| json` always parses.

`tests/unit/test_log_collection.py` keeps the promtail `job` label and the
dashboard's Loki query in lock-step.

A few LogQL queries (Grafana → Explore → Loki, or the dashboard's logs panel):

```logql
{job="quake-feed"} | json                                  # all app logs, parsed
{job="quake-feed"} | json | level="ERROR"                  # errors only
{job="quake-feed", service="celery_worker"} | json         # worker only
{job="quake-feed"} | json | logger="ingest"                # one logger
```

## Reaching it locally

With the stack up (`make up`):

| UI | URL | Notes |
|----|-----|-------|
| Prometheus | http://localhost:9090 | `/targets` should show `backend` and `celery_worker` **UP**. |
| Grafana | http://localhost:3000 | Login from `.env` (`GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD`, default `admin` / `quake`). Open *Quake-feed — Ingestion & Stream Health*. |
| Loki | via Grafana → Explore | No standalone UI; query through Grafana. |

Ports above are the `.env.template` defaults (`PROMETHEUS_PORT`, `GRAFANA_PORT`).

`make metrics` prints the custom metrics from both processes (fetched inside the
compose network, since `:8001` isn't published to the host) plus the UI URLs.
Panels populate once a poll or two has run — the worker polls USGS every 60s.
