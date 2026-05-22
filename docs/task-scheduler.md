# Task scheduler — Celery + RabbitMQ + Beat

Scheduled work runs on **Celery**, with **RabbitMQ** as the broker and **Celery
Beat** as the clock. The only periodic job is the 60-second USGS poll; a
manual `health_check` task is registered for on-demand use. Beat, the worker,
and the API all import the same Celery app from `config.py`.

This document covers (a) the three moving parts and how they're wired, (b) the
registered tasks, (c) the Beat schedule, (d) the kill-switch that can pause
ingestion, and (e) how to run and observe it locally.

## The three processes

One image runs all application roles; they differ only by command
(`docker-compose.yml`):

```
 ┌───────────────┐   amqp://…@rabbitmq:5672//    ┌──────────────┐
 │  celery_beat  │ ───── enqueue poll_usgs ─────►│   RabbitMQ   │
 │  (the clock)  │        every 60 seconds       │   (broker)   │
 └───────────────┘                               └──────┬───────┘
                                                        │ deliver
                                                        ▼
                                                ┌──────────────────┐
                                                │  celery_worker   │
                                                │  --pool=threads  │
                                                │  runs poll_once  │
                                                └──────────────────┘
```

- **`celery_beat`** — `celery -A config.celery_app beat --loglevel=info`. Reads
  the `beat_schedule` and enqueues `poll_usgs` onto the broker on a timer. Beat
  only schedules; it never executes tasks.
- **`celery_worker`** — `celery -A config.celery_app worker --loglevel=info
  --pool=threads`. Consumes from the broker and runs the task body. The
  `--pool=threads` choice is deliberate (see [observability](observability.md)):
  it keeps task execution and the Prometheus exporter in one OS process so they
  share a metrics registry.
- **`rabbitmq`** (`rabbitmq:3-management`) — the AMQP broker. Built from
  `BROKER_URL = amqp://<user>:<pass>@<host>:<amqp_port>//` in `config.py`,
  sourced from the `RABBITMQ_*` env vars (defaults `guest`/`guest`,
  `rabbitmq:5672`). The management UI is on `:15672`.

The Celery app is configured `timezone="UTC"`, `enable_utc=True`,
`task_acks_late=True`, and `worker_prefetch_multiplier=1` — late acks plus a
prefetch of one mean a task is only acknowledged after it finishes, so a worker
crash mid-poll redelivers rather than silently drops. No result backend is
configured: tasks are fire-and-act (they write to the DB), not awaited for a
return value over the broker.

## Registered tasks

Both live in `quake/tasks.py` and register via `@celery_app.task`; `config.py`
loads the module through `include=["quake.tasks"]` so the decorators run on
worker boot.

| Task | Name | Trigger | What it does |
|------|------|---------|--------------|
| `poll_usgs` | `quake.tasks.poll_usgs` | Beat, every 60s | One USGS poll cycle — thin wrapper around `quake.events.ingest.poll_once`, returns the result dict. |
| `health_check` | `quake.tasks.health_check` | On demand | DB liveness probe (`SELECT 1`); returns `{"status": "ok", "ts": …}`. Not scheduled. |

`poll_usgs` is declared `bind=True, max_retries=0`. Retries are **off on
purpose**: retry/backoff already lives inside `UsgsClient`, and a Celery-level
retry would double-retry and double-record the ingestion run. The actual
work — fetch → parse → upsert → count revisions → stamp `quake.ingestion_runs`
— is described in [`docs/architecture.md`](architecture.md); the scheduler just
fires it.

## The Beat schedule

Defined inline in `config.py`:

```python
beat_schedule = {
    "poll_usgs_every_60s": {
        "task": "quake.tasks.poll_usgs",
        "schedule": 60.0,
    },
}
```

A single entry: `poll_usgs` on a fixed 60-second interval, matching the USGS
realtime feed's 1-minute refresh cadence. The interval is a plain float, not a
cron expression.

For cron-style scheduling there's a helper, `crontab_or_default(env_var,
default)` in `functions/scheduler.py`, which reads a 5-field cron string from
the environment (falling back to a default) and returns a Celery `crontab`.
The current single-interval schedule doesn't use it — it's there for when a
future task needs wall-clock scheduling (e.g. a nightly maintenance job)
without hardcoding the expression.

## Pausing ingestion — the kill switch

`poll_once` checks the `INGESTION_LOCK` flag in `quake.endpoint_locks` before
doing any work. When an operator sets the lock via the admin endpoint
(`/admin/locks`), the next poll records a *skipped* run in
`quake.ingestion_runs` and returns immediately — no `UsgsClient` is opened and
USGS is never hit. Beat keeps enqueuing on schedule; each fire just no-ops
until the lock is cleared. This is the clean way to halt ingestion without
stopping the worker.

## Running and observing locally

`make up` starts `celery_worker` and `celery_beat` alongside the rest of the
stack; `make logs` tails them. Things to watch:

- **RabbitMQ management UI** — `http://localhost:15672` (default `guest`/`guest`):
  queues, message rates, consumer count.
- **Worker metrics** — the worker exposes its Prometheus registry on
  `WORKER_METRICS_PORT` (default `8001`) via a `worker_init` hook in
  `functions/celery_metrics.py`; Prometheus scrapes it as `celery_worker:8001`.
  Per-task `celery_task_total` / `celery_task_duration_seconds` plus the
  ingestion metrics are published there. See [`docs/observability.md`](observability.md).
- **Ingestion log** — every poll (including skipped ones) lands a row in
  `quake.ingestion_runs`, the durable audit log behind `/admin/ingest/status`.
  (The Grafana ingestion dashboard itself is metric-driven via Prometheus, not a
  query on this table — see [`docs/observability.md`](observability.md).)
- **Manual trigger** — the admin ingest endpoint can run a poll out of band
  (`/admin/ingest/trigger`) without waiting for Beat.

## Related

- [`docs/architecture.md`](architecture.md) — the full ingestion data flow `poll_once` drives.
- [`docs/observability.md`](observability.md) — worker metrics topology and the `--pool=threads` rationale.
- [`docs/database-migrations.md`](database-migrations.md) — the `ingestion_runs` and `endpoint_locks` tables this scheduler writes.
