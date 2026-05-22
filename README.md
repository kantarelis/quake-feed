# 🌋 quake-feed

> **FastAPI + TimescaleDB + Celery + RabbitMQ + Vault + Prometheus + Grafana + Loki + React/Leaflet**
>
> A real-time public earthquake data service: USGS realtime feed → ingestion → TimescaleDB → read API + SSE alerts + a live map dashboard. Containerized, observable, and runnable on a laptop with one `make up`.

[![CI](https://github.com/kantarelis/quake-feed/actions/workflows/code_quality_assurance.yml/badge.svg)](https://github.com/kantarelis/quake-feed/actions/workflows/code_quality_assurance.yml)
![Coverage](coverage.svg)

---

## 🧭 Table of Contents

- [🏗️ Overview](#overview)
- [📁 Project Structure](#project-structure)
- [⚙️ Prerequisites](#prerequisites)
- [🚀 Quick Start](#quick-start)
- [🧰 Development Utilities](#development-utilities)
- [📊 Services Stack](#services-stack)
- [🧹 Maintenance](#maintenance)
- [📚 Documentation](#documentation)
- [🧩 Tech Stack](#tech-stack)
- [🎯 What this demonstrates](#what-this-demonstrates)
- [🧠 Notes](#notes)
- [📜 License](#license)


<a id="overview"></a>

## 🏗️ Overview

`quake-feed` ingests the USGS realtime earthquake feed on a 60-second cadence, deduplicates events against their USGS event ID, and tracks magnitude/depth revisions over time in a TimescaleDB hypertable. It serves:

- A **REST API** (`/events/recent`, `/events?near=lat,lon&radius_km=R`, `/events?min_magnitude=X&since=T`)
- A **Server-Sent Events** stream (`/alerts/stream`) that pushes new events matching per-client filters in real time
- A **React + Leaflet** dashboard with a live map and a recent-events timeline

The stack is intentionally a clean public mirror of a production backend architecture (Manager/Views, dbmate migrations, Celery+RabbitMQ scheduling, Vault-backed secrets, Loki/Prometheus/Grafana observability), reskinned onto a public, no-friction dataset.

All services are orchestrated via `docker-compose`; development utilities are managed through a Makefile. Deployment is **local-only** — no cloud accounts required.


<a id="project-structure"></a>

## 📁 Project Structure

```
quake-feed/
│
├── quake/                  # FastAPI app and API routes (Manager/Views pattern)
│   ├── api/                # One subdir per API module
│   ├── ingestion/usgs/     # USGS GeoJSON client + parsers
│   ├── events/             # Events business logic (dedupe, upsert, revisions)
│   ├── alerts/             # In-process SSE subscriber registry + filter matcher
│   └── tasks.py            # Celery scheduled tasks
├── database/               # dbmate migrations + ETL pipelines
├── functions/              # Shared utilities (env, logger, vault, scheduler)
├── models/                 # Pydantic data models
├── monitoring/             # Grafana, Loki, Prometheus configurations
├── frontend/               # React + Vite + Leaflet dashboard
├── docs/                   # Extended documentation
├── tests/                  # unit / integration / fixtures
├── docker-compose.yml      # Multi-container configuration
├── makefile                # Dev tools and Docker management
├── requirements*.txt       # Production / dev / test dependencies
├── .env.template           # Environment variable template
└── __main__.py             # Application entry point
```


<a id="prerequisites"></a>

## ⚙️ Prerequisites

- [Python 3.14](https://www.python.org/downloads/)
- [Docker & Docker Compose](https://docs.docker.com/get-docker/)
- [Make](https://www.gnu.org/software/make/)
- [dbmate](https://github.com/amacneil/dbmate) — for database schema migrations (`sudo pacman -S dbmate` on Arch, `brew install dbmate` on macOS)
- [Node.js 20+](https://nodejs.org/) — only if you want to run the frontend dev server (`make frontend-dev`). The production build is served by the backend container and needs no host Node.


<a id="quick-start"></a>

## 🚀 Quick Start

### 1. Install dependencies

```bash
make install         # for production
make install-test    # for testing
make install-dev     # for development
```

### 2. Create and configure environment file

```bash
make install-env
```

This creates a `.env` file from `.env.template`. Edit it to match your local configuration (the defaults work for the docker-compose stack).

### 3. Start the services

```bash
make up
```

Brings up the backend, Celery worker, Celery beat, TimescaleDB, RabbitMQ, Vault, Prometheus, Grafana, and Loki.

### 4. Initialize and unseal Vault (first time only)

```bash
make vault-init      # writes unseal keys + root token to vault_init_output.txt
make vault-unseal    # uses keys from .env (VAULT_UNSEAL_KEYS)
```

After every container restart, Vault comes up sealed — re-run `make vault-unseal`.

### 5. Apply database migrations

On a fresh local stack (first `make up`, or after `make clean`):

```bash
make db-migrate
```

This runs `dbmate up` against the local TimescaleDB and applies every migration in `database/migrations/`.

### 6. Issue an API key

```bash
make issue-api-key
```

Prints a new API key once (it's hashed in the DB and stored raw in Vault). Use it as `Authorization: Bearer <key>` for protected endpoints.

### 7. Inspect

| What | URL |
|------|-----|
| API docs | http://localhost:8000/docs |
| Frontend | http://localhost:8000/ (production build) or http://localhost:5173 (`make frontend-dev`) |
| Grafana | http://localhost:3000 (default credentials in `.env.template`) |
| Prometheus | http://localhost:9090 |
| RabbitMQ management | http://localhost:15672 |


<a id="development-utilities"></a>

## 🧰 Development Utilities

### 🧪 Static Analysis

```bash
make check    # Run linters and type checks
make format   # Auto-format code (isort + black)
```

Tools: **isort**, **black**, **flake8**, **mypy**, **bandit**.

### 🧪 Tests

```bash
make test           # Run pytest
make test-report    # Run with HTML coverage report
```

### 🗃️ Database Migrations

```bash
make db-migrate     # Apply pending migrations to the local DB
make migrate-test   # Sandbox-test migrations: cold start + rollback + re-apply
make db-schema      # Dump live schema to database/schema.sql (gitignored)
```

Full workflow in [`docs/database-migrations.md`](docs/database-migrations.md).

### 🔐 Vault

```bash
make vault-status   # Show seal status
make vault-init     # First-time initialization (writes keys to vault_init_output.txt)
make vault-unseal   # Unseal using keys from .env
make vault-seal     # Re-seal (needs VAULT_TOKEN)
```


<a id="services-stack"></a>

## 📊 Services Stack

| Service        | Default Port  | Description                            |
| -------------- | ------------- | -------------------------------------- |
| **FastAPI**    | `8000`        | Backend API + SSE + frontend assets    |
| **PostgreSQL** | `5432`        | TimescaleDB time-series database       |
| **RabbitMQ**   | `5672/15672`  | Message broker (AMQP / Management UI)  |
| **Vault**      | `8200`        | Secrets management (dev mode)          |
| **Prometheus** | `9090`        | Metrics collection                     |
| **Grafana**    | `3000`        | Dashboards (provisioned from `monitoring/grafana/`) |
| **Loki**       | `3100`        | Log aggregation                        |


<a id="maintenance"></a>

## 🧹 Maintenance

| Command             | Description                                     |
| ------------------- | ----------------------------------------------- |
| `make reset`        | Full restart (down + clean + up)                |
| `make clean`        | Stop containers, remove volumes & orphans       |
| `make prune`        | Full Docker cleanup (`docker system prune -af`) |
| `make clean-logs`   | Wipe Loki + Prometheus data only                |


<a id="documentation"></a>

## 📚 Documentation

Operational and architectural deep-dives live in [`docs/`](docs/):

| Topic | Document |
| ----- | -------- |
| Architecture diagram and data flow | [`docs/architecture.md`](docs/architecture.md) |
| Database schema migrations (dbmate workflow) | [`docs/database-migrations.md`](docs/database-migrations.md) |
| HashiCorp Vault (lifecycle, secret layout) | [`docs/vault.md`](docs/vault.md) |
| Task scheduler (Celery + RabbitMQ + Beat) | [`docs/task-scheduler.md`](docs/task-scheduler.md) |
| Alerts SSE (in-process pub/sub, filter matcher) | [`docs/alerts.md`](docs/alerts.md) |
| Observability (Prometheus metrics, Grafana dashboard, Loki logs) | [`docs/observability.md`](docs/observability.md) |
| Frontend dashboard (React + Vite + Leaflet) | [`docs/frontend.md`](docs/frontend.md) |


<a id="tech-stack"></a>

## 🧩 Tech Stack

* **Language**: Python 3.14
* **Framework**: FastAPI + Uvicorn
* **Database**: PostgreSQL with TimescaleDB (time-series)
* **Task Queue**: Celery + RabbitMQ
* **Realtime web**: Server-Sent Events via `sse-starlette`
* **Auth**: API-key (Bearer header), validated against a Vault-backed key set
* **Secrets**: HashiCorp Vault
* **Monitoring**: Prometheus, Loki, Grafana
* **Frontend**: React + Vite + TypeScript + Leaflet
* **Tooling**: Makefile, Docker Compose
* **Static Analysis**: isort, black, flake8, mypy, bandit


<a id="what-this-demonstrates"></a>

## 🎯 What this demonstrates

A single artifact aimed at recruiters scanning for backend / full-stack / data engineering signal.

| Role | What you'll find here |
| ---- | ---------------------- |
| **Software Engineer** | Typed Python 3.14, isort/black/flake8/mypy/bandit-gated CI, tested with pytest, clean module boundaries, Manager/Views separation. |
| **Backend Engineer** | FastAPI service with REST + SSE, API-key auth dependency, Celery+RabbitMQ task scheduling, Vault-backed secret handling, observability via Prometheus/Grafana/Loki. |
| **Full-Stack Engineer** | React + Vite + TypeScript + Leaflet dashboard with a live map, recent-events timeline, and an alert-config form backed by the SSE stream. |
| **Data Engineer** | dbmate-versioned schema, TimescaleDB hypertable design, ingestion worker with dedupe + revision tracking (USGS refines magnitudes after the initial report), per-poll ingestion log for ops dashboards. |


<a id="notes"></a>

## 🧠 Notes

* Always ensure your `.env` is properly configured before running the app.
* Monitoring stack (Grafana, Loki, Prometheus) auto-starts with `make up`.
* Vault starts sealed after each restart — run `make vault-unseal`.
* Data source: [USGS Earthquake Hazards Program](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php) (public domain, no API key required).


<a id="license"></a>

## 📜 License

MIT — see [LICENSE](LICENSE).
