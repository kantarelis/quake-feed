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
| 3 | `docs/architecture.md` — Mermaid diagram + data-flow walkthrough | ✅ Done | `addc29e` |
| 4 | Polish + connect existing docs (`vault.md`, `alerts.md`, orphaned `frontend.md`) | ✅ Done | `23c1091` |
| 5 | README content polish + demo GIF embed + `docs/assets/` | ✅ Done | `d11a4f3` |
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

## Task 3 — `docs/architecture.md` ✅ `addc29e`

**Outcome.** Authored the keystone `docs/architecture.md`: a **Mermaid `flowchart`** component map (renders natively on GitHub) plus the three data-flow walkthroughs and a subsystem deep-dive hub. Verified the read/alert paths against code before drawing — read `quake/main.py`, `quake/alerts/listener.py`, `quake/events/ingest.py`, `quake/api/ingest/views.py`, `docker-compose.yml`, and the Grafana provisioning. The diagram edges are accurate (`AFTER INSERT · pg_notify → AlertListener`, `AFTER UPDATE → event_revisions`, admin manual trigger → RabbitMQ via `send_task`, Prometheus scraping `backend:8000` + `celery_worker:8001`). Walkthroughs: ingestion (Beat → broker → `poll_once` → lock gate → fetch/parse → upsert → triggers → run stamp), read (auth → Manager/Views → `EventsETL.query()` → `EventResponse`), alert (NOTIFY → listener → registry/matcher → SSE, single-pod note). Resolves the last of the three dead README/CLAUDE links and the within-branch `architecture.md` links from Tasks 1–2. `make check` + `make test` green.

**Deviations.**
- Auth drawn as a component with its validation backends (`api_keys`, Vault) rather than an edge from every endpoint — diagram legibility; precision carried in prose.
- **Correctness finding (logged for follow-up):** verified Grafana has only **Prometheus + Loki** datasources (no Postgres), so Task 2's phrasing that `ingestion_runs` "drives" the dashboard is misleading — the dashboard is metric-driven; `ingestion_runs` is the audit log / `/admin/ingest/status` source. `architecture.md` states this correctly; the committed `task-scheduler.md` line was left as-is (separate commit, user's call to amend).

---

## Task 4 — Polish + connect existing docs ✅ `23c1091`

**Outcome.** Connected and corrected the existing docs. **`vault.md`:** removed two stale `*(landing in Task 2)*` tags (Epic 5 leftovers, now misleading) and added a "Listing & pruning" section for the `make list-api-keys` / `make prune-api-keys` targets that post-dated the doc — verified against the actual makefile help strings. **`alerts.md`:** accurate as-is, added a Related footer. **`frontend.md`:** added a Related footer (no content rewrite, per spec). **`README.md` + `CLAUDE.md`:** added the orphaned `frontend.md` to both doc tables and the missing `observability.md` to the CLAUDE.md subsystems table. Verified: all 7 `docs/*.md` reachable from README/CLAUDE, every inter-doc relative link resolves, no stale "landing in Task" tags remain. `make check` + `make test` green.

**Deviations.**
- Went slightly beyond the "light pass" spec on `vault.md` by adding the list/prune section — the API-key lifecycle the doc owns was genuinely incomplete without it.
- Edited `CLAUDE.md` (a project-instruction file) — only the subsystems-table rows, as the spec directed.

---

## Task 5 — README content polish + demo GIF ✅ `d11a4f3`

**Outcome.** Added a **🎬 Demo** TOC entry + section near the top embedding `docs/assets/demo.gif` (`<img>` at `width="820"`, descriptive alt text, an HTML comment flagging the GIF as hand-recorded). Rebuilt **"What this demonstrates"** as a 3-column table with a **"Where to look"** column pointing each role at concrete, verified paths (`quake/api/auth.py`, `quake/tasks.py` + `config.py`, `functions/vault.py`, `functions/metrics.py`, `database/migrations/`, `quake/events/ingest.py`, …). Wrote `docs/assets/RECORDING.md` with the capture recipe. The GIF was then **recorded by Spyro** (Hyprland: `wf-recorder` + `slurp`) and produced via the ffmpeg two-pass palette pipeline — including a cut removing the 0:47–0:56 segment (68s → 59s), final `demo.gif` 820×439, ~5.1 MB. `make check` + `make test` green.

**Deviations.**
- Dropped the planned `docs/assets/.gitkeep` — `RECORDING.md` already tracks the directory, so it would be dead weight.
- Added `docs/assets/*.mp4|mov|webm` to `.gitignore` so the heavy 7.8 MB recording master stays local; only the embedded GIF is tracked. (Not in the original spec; the right call for repo size.)
- The committed `RECORDING.md` still describes the OBS/x11grab/Peek approach rather than the `wf-recorder` flow that actually worked — see open item below.

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

- **`RECORDING.md` decision (open, to fold into Task 6):** now that `demo.gif` exists, `docs/assets/RECORDING.md` is no longer needed for its original purpose, and as committed it documents the wrong tools (OBS / ffmpeg x11grab / Peek) instead of the `wf-recorder` + ffmpeg-palette flow that actually worked. Pending choice: (1) remove it + drop the README "How the clip is produced" link; (2) keep it as an unadvertised maintainer note, drop the README link, and correct it to the real flow; or (3) keep + keep the link, corrected. Whichever is chosen, do it in the Task 6 commit and re-check links.
- **Task 2 wording follow-up (minor):** `task-scheduler.md` says `ingestion_runs` "drives" the Grafana dashboard; it's actually metric-driven (Grafana has no Postgres datasource). Optional one-line amend in a follow-up; `architecture.md` already states it correctly.
- **Epic 8 archive (carried over):** `MASTER_PLAN.md` flags the Epic 8 `PLAN.md` archive to `docs/history/epic-08-observability.md` as *pending*, but the root `PLAN.md` is already empty and `docs/history/` is empty — the Epic 8 plan content now only exists in merged PR #8 history. Recovering and archiving it (and likewise the Epic 6/7 plans the MASTER_PLAN references) is a separate user decision, not part of Epic 9. Flagged here so it isn't lost.
- **Out of scope:** any code/behavior changes beyond the doc-integrity test; final GitHub publication / repo-pinning (explicitly a user action per MASTER_PLAN).
