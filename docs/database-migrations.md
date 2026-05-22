# Database migrations — dbmate workflow & schema management

The schema lives in **versioned, forward-only SQL migrations** under
`database/migrations/`. [dbmate](https://github.com/amacneil/dbmate) is the
single source of truth: there is no ORM-managed schema and no hand-edited
canonical `schema.sql`. Every structural change — a new table, an index, a
trigger — is a new timestamped migration file.

This document covers (a) the migration file layout, (b) authoring a new
migration, (c) the three Make targets and what each one does, (d) the
`public.schema_migrations` quirk and why it's mandatory, and (e) the
on-demand schema dump.

## Layout

```
database/
├── migrations/
│   ├── 20260516170000_baseline.sql        # quake schema, tables, hypertable, revision trigger
│   └── 20260519154655_events_notify.sql   # pg_notify trigger feeding the SSE listener
├── .dbmate.yml                             # reference config (not auto-loaded — see below)
├── schema.sql                              # gitignored; produced on demand by `make db-schema`
└── _pretty_schema.py                       # re-orders/de-noises the schema dump in place
```

Each migration file has two halves dbmate reads by marker comment:

```sql
-- migrate:up
CREATE TABLE IF NOT EXISTS quake.some_table ( ... );

-- migrate:down
DROP TABLE IF EXISTS quake.some_table;
```

Migrations are **forward-only** in normal operation — `down` exists so the
sandbox test can prove each migration is reversible, not because we roll back
production data. Apply order is the timestamp prefix, so files sort
chronologically.

## Authoring a migration

Create a new file with a host dbmate install:

```bash
dbmate new add_some_column
# → database/migrations/YYYYMMDDHHMMSS_add_some_column.sql
```

(The Make targets that *apply*, *test*, and *dump* run dbmate from a pinned
Docker image so they need no host install — see below. `dbmate new` just
stamps an empty file, so a host binary or copying the timestamped-filename
pattern by hand both work.)

Then fill both halves. Two rules:

- **Guard every statement** with `IF [NOT] EXISTS` (or `CREATE OR REPLACE`
  for functions, `DROP TRIGGER IF EXISTS` before `CREATE TRIGGER`). The
  sandbox test re-applies the newest migration, so a non-idempotent `up` will
  fail it.
- **Write a working `down`.** It must cleanly reverse `up`. The baseline's
  `down`, for example, drops the trigger and function before the tables and
  finishes with `DROP SCHEMA IF EXISTS quake CASCADE`.

The two current migrations are good templates: `20260516170000_baseline.sql`
creates the `quake` schema, the `events` hypertable, the supporting tables,
and the magnitude/depth/place **revision trigger** (thresholds inlined in the
migration per project convention); `20260519154655_events_notify.sql` adds the
`AFTER INSERT` `pg_notify` trigger that feeds the alerts listener.

## The Make targets

All three load `DATABASE_URL` and invoke dbmate through the
`amacneil/dbmate:latest` Docker image (`--network host`, with `database/`
mounted at `/db`), always passing:

```
--migrations-dir /db/migrations
--schema-file    /db/schema.sql
--migrations-table public.schema_migrations
```

### `make db-migrate` — apply to the local stack

```bash
make db-migrate
```

Reads `.env`, builds `DATABASE_URL` from `DB_USERNAME` / `DB_PASSWORD` /
`DB_PORT` / `DB_NAME`, and runs `dbmate up` against the running compose DB on
`127.0.0.1:5432`. Run it on a fresh stack (first `make up`, or after
`make clean`) and whenever new migrations land.

### `make migrate-test` — sandbox the migration cycle

```bash
make migrate-test
```

Spins up a **throwaway** TimescaleDB on `:5433`, waits for it to accept
connections, then exercises the full cycle against it:

```
dbmate up    # cold start — apply every migration from empty
dbmate down  # roll back the newest migration
dbmate up    # re-apply the newest migration
```

This proves three things at once: every migration applies cold, the newest
one's `down` works, and its `up` is idempotent (re-applying is safe). The
throwaway container is removed via an `EXIT` trap even if the test fails, so
it never collides with the real stack. This target is the migration gate in
CI.

### `make db-schema` — dump the schema for inspection

```bash
make db-schema
```

Runs `dbmate dump` against the local DB to write `database/schema.sql`, then
runs `python -m database._pretty_schema` to re-order and de-noise it in place.
`schema.sql` is **gitignored** — it's a generated, human-readable snapshot for
inspection and diffing, never the source of truth and never committed. The
migrations are. `_pretty_schema.py` strips pg_dump's preamble/`COMMENT`/meta
noise, sorts blocks into a stable category order (schema → extension →
function → table → … → trigger), and preserves dbmate's
`schema_migrations` footer verbatim; its output is idempotent, so back-to-back
runs produce identical bytes.

## The `public.schema_migrations` quirk

dbmate tracks applied migrations in a `schema_migrations` table. By default it
places that table in the first schema on the connection's `search_path`.
Postgres's default `search_path` is `"$user", public`, and our DB user is
`quake` with a `quake` schema created by the baseline — so the default
resolves to **`quake.schema_migrations`**, which doesn't exist yet on the very
first `dbmate up`, and the cold-start fails with:

```
relation "quake.schema_migrations" does not exist
```

Pinning `--migrations-table public.schema_migrations` keeps dbmate's
bookkeeping in `public` (which always exists) and sidesteps the bootstrap
problem. **Always pass this flag.** The Make targets already do; `.dbmate.yml`
records the same value but is *not* auto-loaded by dbmate — it exists for
editor plugins and as a single readable place for the canonical settings, with
the Make targets passing every flag explicitly so behavior never depends on a
file dbmate might or might not pick up.

## Related

- [`docs/architecture.md`](architecture.md) — where the schema sits in the overall data flow.
- [`docs/observability.md`](observability.md) — how `quake.ingestion_runs` feeds the ingestion dashboard.
- [`docs/vault.md`](vault.md) — DB credentials are sourced alongside the API-key material.
