# PLAN.md — Epic 9: Documentation polish + architecture diagram + demo GIF

Active epic from [`MASTER_PLAN.md`](MASTER_PLAN.md). Branch: `polish-documentation-and-architecture-diagram`.

**Goal.** Close the documentation gaps so the repo reads cleanly to a recruiter or engineer landing on it cold: every doc linked from `README.md` and `CLAUDE.md` exists and is accurate, the architecture is shown as a diagram + data-flow walkthrough, the README's "What this demonstrates" table points at concrete files, a demo GIF shows the live map, and a test guards against doc-link rot regressing.

**Starting state (verified 2026-05-22).**
- **Missing docs (dead links in both README + CLAUDE.md):** `docs/architecture.md`, `docs/database-migrations.md`, `docs/task-scheduler.md`.
- **Present docs:** `docs/alerts.md` (Epic 6), `docs/vault.md` (Epic 5), `docs/observability.md` (Epic 8), `docs/frontend.md` (Epic 7). `frontend.md` is **orphaned** — not listed in either doc table.
- **README:** "What this demonstrates" table exists but is prose-only (no file/commit references); no demo GIF; no `docs/assets/` directory.

**Constraints.**
- Docs-only tasks aren't touched by the Python linters in `make check` (isort/black/flake8/mypy/bandit), but every task still runs `make check` + `make test` to confirm no regression. The real test gate for this epic is the doc-integrity test added in Task 6.
- **The demo GIF binary cannot be produced by Claude** (it needs a screen capture of the running stack). Task 5 scaffolds the embed, the `docs/assets/` location, and exact recording commands; Spyro records and drops in the file.
- All docs cross-link with relative paths and stay consistent with the current code/makefile — no aspirational claims.

---

## Progress

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | `docs/database-migrations.md` — dbmate deep-dive | ✅ Done | `db54b31` |
| 2 | `docs/task-scheduler.md` — Celery + RabbitMQ + Beat deep-dive | ✅ Done | `d4e64cd` |
| 3 | `docs/architecture.md` — Mermaid diagram + data-flow walkthrough | ⬜ Not started | — |
| 4 | Polish + connect existing docs (`vault.md`, `alerts.md`, orphaned `frontend.md`) | ⬜ Not started | — |
| 5 | README content polish + demo GIF embed + `docs/assets/` | ⬜ Not started | — |
| 6 | Doc-integrity test + final dead-link/screenshot sweep (epic close-out) | ⬜ Not started | — |

**Status legend:** ⬜ Not started · 🟡 In progress · ✅ Done

---

## Task 1 — `docs/database-migrations.md` ✅ `db54b31`

**Outcome.** Authored `docs/database-migrations.md` in the house doc style (H1 title + "this document covers (a)…(e)" intro). Content was sourced by reading `makefile`, `database/.dbmate.yml`, both migration files, and `_pretty_schema.py` — not from memory. Covers: file layout + the two current migrations as templates; authoring (`dbmate new`, up/down markers, idempotency guards); the three Make targets with exact behavior (`db-migrate` → `.env`→`DATABASE_URL`→`dbmate up` on `:5432`; `migrate-test` → throwaway `:5433`, up→down→up, EXIT-trap cleanup, CI gate; `db-schema` → `dbmate dump` + `_pretty_schema.py`, gitignored output); and the `--migrations-table public.schema_migrations` quirk with the real `relation "quake.schema_migrations" does not exist` failure and why `.dbmate.yml` isn't auto-loaded. One of the three dead doc links is now live. `make check` + `make test` green (231 unit + 4 integration; no Python touched).

**Deviations.**
- Clarified the **host-vs-Docker** split that neither CLAUDE.md nor README spell out: `dbmate new` stamps a file (host binary or by-hand pattern), while the Make targets run the pinned `amacneil/dbmate:latest` image. Not in the original task bullets but necessary for accuracy.
- The "Related" block links `docs/architecture.md`, which doesn't exist until Task 3 — an intentional within-branch dead link that resolves by epic end (anticipated in the original acceptance criteria).

---

## Task 2 — `docs/task-scheduler.md` ✅ `d4e64cd`

**Outcome.** Authored `docs/task-scheduler.md` in the same style. Sourced from `config.py`, `quake/tasks.py`, `functions/scheduler.py`, `functions/celery_metrics.py`, `docker-compose.yml`, and `.env.template`. Covers: the three processes (`celery_beat`/`celery_worker`/`rabbitmq`) with exact compose commands and the `--pool=threads` rationale (cross-linked to observability, not restated); Celery app config (`BROKER_URL` shape, `task_acks_late`, `worker_prefetch_multiplier=1`, UTC, **no result backend**); both registered tasks in a table (`poll_usgs` Beat-60s `bind=True, max_retries=0` and why retries are off; `health_check` on-demand, not scheduled); the Beat schedule verbatim (single `60.0` interval); the `INGESTION_LOCK` kill-switch path through `poll_once` (records a *skipped* run, no USGS hit); and local observation (RabbitMQ UI `:15672`, worker metrics `:8001` via the `worker_init` hook, `ingestion_runs` log, manual trigger). Second dead link now live. `make check` + `make test` green.

**Deviations.**
- `functions/scheduler.py::crontab_or_default` is **defined but unused** (the live schedule uses a plain `60.0`). Documented honestly as an available helper for future cron-style entries rather than implying it's wired in — avoids documenting dead code as active.
- Same intentional within-branch `architecture.md` cross-link as Task 1.

---

## Task 3 — `docs/architecture.md`

The architecture diagram + data-flow walkthrough — the keystone doc linked first in both doc tables.

**Scope (files):**
- `docs/architecture.md` (new).

**Content:**
- A **Mermaid** diagram (fenced ```mermaid block — GitHub renders it natively) showing: USGS feed → Celery worker (Beat 60s) → TimescaleDB; FastAPI read API + SSE; in-process pub/sub from upsert → SSE subscribers; frontend; and the side systems (Vault for secrets, Prometheus/Grafana/Loki for observability, RabbitMQ as Celery broker).
- Three data-flow walkthroughs in prose: **ingestion path** (poll → parse → dedupe/revision → upsert → `ingestion_runs`), **read path** (`/events*` query → ETL → DTO), **alert path** (upsert → NOTIFY/in-process publish → `FilterMatcher` → `/alerts/stream`).
- A "see also" block linking each subsystem to its deep-dive (`database-migrations.md`, `task-scheduler.md`, `vault.md`, `alerts.md`, `observability.md`, `frontend.md`).

**Acceptance criteria:**
- Mermaid block is syntactically valid (renders on GitHub); diagram matches the actual component/data flow described in `CLAUDE.md` + code.
- All "see also" links resolve.
- README + CLAUDE.md links to this file now resolve.

**Checks:** `make check` + `make test` pass.

---

## Task 4 — Polish + connect existing docs

Finalize the docs written in earlier epics and connect the orphaned one, so the docs form one navigable set.

**Scope (files):**
- `docs/vault.md`, `docs/alerts.md` — light accuracy/consistency pass (verify against current code; consistent headers; add cross-links to `architecture.md` and siblings).
- `docs/frontend.md` — add a cross-link header consistent with the others (no content rewrite).
- `README.md` + `CLAUDE.md` — add `docs/frontend.md` to the documentation / subsystems tables so it's no longer orphaned (and confirm `observability.md` is present in both — already in README, check CLAUDE.md).

**Acceptance criteria:**
- `vault.md` / `alerts.md` claims still match code (e.g. secret paths, filter semantics); any drift fixed.
- Every doc under `docs/` is reachable from at least one of README/CLAUDE.md.
- All cross-links resolve.

**Checks:** `make check` + `make test` pass.

---

## Task 5 — README content polish + demo GIF

Make the README's headline section concrete and add the demo GIF.

**Scope (files):**
- `README.md` — flesh out "What this demonstrates" so each row points at concrete files/dirs (e.g. `quake/api/auth.py`, `database/migrations/`, `quake/alerts/`); add a "Demo" section near the top embedding the GIF.
- `docs/assets/` (new dir) — `.gitkeep` + a short `RECORDING.md` with the exact capture commands (e.g. `peek` / `ffmpeg` / browser screen-record → optimized gif), target dimensions, and what the clip should show (live map receiving an SSE event, recent-events timeline).
- Embed path: `docs/assets/demo.gif` (relative), with descriptive alt text and a sensible width.

**Demo GIF reality:** the binary `demo.gif` is **recorded and committed by Spyro** — this task wires the markdown, the assets location, and the instructions; it does not (cannot) produce the GIF. Until the file lands the embed will show broken-image alt text, which is expected and called out in `RECORDING.md`.

**Acceptance criteria:**
- "What this demonstrates" rows reference real paths that exist in the repo.
- README has a Demo section with the GIF embed + alt text; `docs/assets/RECORDING.md` gives reproducible capture steps.
- No new dead links (the GIF path is documented as user-supplied).

**Checks:** `make check` + `make test` pass.

---

## Task 6 — Doc-integrity test + final sweep (epic close-out)

Add a test that prevents doc-link rot from regressing, then do the final polish pass.

**Scope (files):**
- `tests/unit/test_docs_links.py` (new) — asserts every `docs/*.md` path referenced in `README.md` and `CLAUDE.md` exists on disk (the exact failure this epic started from). Fast, no I/O beyond reading the two files + `os.path.exists`. Follows the unit-test <2s rule.
- Any straggler fixes surfaced by a manual dead-link sweep across `README.md`, `CLAUDE.md`, and `docs/`.

**Acceptance criteria:**
- New test fails if any README/CLAUDE-referenced `docs/*.md` is missing, and passes on the current tree.
- Manual sweep: no remaining dead relative links; screenshot/asset references current.
- `make check` + `make test` pass, including the new test.

**Checks:** `make check` + `make test` pass.

---

## Notes / open items

- **Epic 8 archive (carried over):** `MASTER_PLAN.md` flags the Epic 8 `PLAN.md` archive to `docs/history/epic-08-observability.md` as *pending*, but the root `PLAN.md` is already empty and `docs/history/` is empty — the Epic 8 plan content now only exists in merged PR #8 history. Recovering and archiving it (and likewise the Epic 6/7 plans the MASTER_PLAN references) is a separate user decision, not part of Epic 9. Flagged here so it isn't lost.
- **Out of scope:** any code/behavior changes beyond the doc-integrity test; the actual GIF recording (user action); final GitHub publication / repo-pinning (explicitly a user action per MASTER_PLAN).
