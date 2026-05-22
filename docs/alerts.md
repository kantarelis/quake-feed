# Alerts SSE — pipeline design & filter semantics

`/alerts/stream` pushes new earthquakes to connected clients in realtime over
Server-Sent Events. A client first registers one or more **filters** via
`/alerts/filters`; the stream then delivers only the events that match.

This document covers (a) how an event gets from the ingestion worker to a
connected browser, (b) what "matches" means, and (c) the single-pod limit and
its migration path.

## The pipeline

```
 ┌─────────────────┐   INSERT     ┌──────────────────────┐
 │  Celery worker  │ ───────────► │   quake.events       │
 │ (USGS poll/60s) │              │   (TimescaleDB)      │
 └─────────────────┘              └──────────┬───────────┘
                                             │ AFTER INSERT FOR EACH ROW
                                             ▼
                                  ┌──────────────────────┐
                                  │ quake.events_notify() │  trigger fn
                                  │  pg_notify(            │
                                  │   'quake_event_inserts'│
                                  │   row_to_json(NEW))    │
                                  └──────────┬───────────┘
              ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─  Postgres LISTEN/NOTIFY
              process boundary               │        (the cross-process hop)
                                             ▼
 ┌───────────────────────────  API process  ─────────────────────────────┐
 │                                           │                            │
 │                              ┌────────────▼───────────┐                │
 │                              │     AlertListener       │  one async    │
 │                              │  LISTEN quake_event_... │  task, owned   │
 │                              │  decode → EventRow      │  by lifespan   │
 │                              └────────────┬───────────┘                │
 │                                           │ registry.publish(event)    │
 │                              ┌────────────▼───────────┐                │
 │                              │   SubscriberRegistry    │  module-level  │
 │                              │  walk every slot, run   │  singleton     │
 │                              │  FilterMatcher (OR)     │                │
 │                              └────────────┬───────────┘                │
 │                                           │ put_nowait(envelope)        │
 │              ┌───────────────┬────────────┴──────────┬─────────────┐   │
 │              ▼               ▼                        ▼             │   │
 │        asyncio.Queue   asyncio.Queue            asyncio.Queue       │   │
 │              │               │                        │             │   │
 │              ▼               ▼                        ▼             │   │
 │     EventSourceResponse  EventSourceResponse   EventSourceResponse  │   │
 │      (SSE client A)       (SSE client B)         (SSE client C)      │   │
 └────────────────────────────────────────────────────────────────────┘
```

| Stage | Code |
|-------|------|
| Trigger + notify fn | `database/migrations/20260519154655_events_notify.sql` |
| LISTEN task | `quake/alerts/listener.py` (`AlertListener`) |
| Lifespan wiring | `quake/main.py` (`Quake._lifespan`) |
| In-process fanout | `quake/alerts/registry.py` (`SubscriberRegistry`) |
| Match logic | `quake/alerts/matcher.py` (`matches`) |
| Filter CRUD + SSE views | `quake/api/alerts/{main,views}.py` |
| Wire models | `models/alerts.py` (`AlertFilter`, `AlertFilterResponse`, `AlertEnvelope`) |

## Why LISTEN/NOTIFY?

The Celery worker and the API run as **separate OS processes** (separate
containers, in fact). An "in-process queue" can't span them — the event has to
cross a process boundary somewhere. The options were:

- **A new broker topic on RabbitMQ.** RabbitMQ is already in the stack for
  task scheduling, but wiring a fanout exchange + a consumer into the API
  process is real infrastructure: a second connection to manage, a second
  failure mode, and a consumer loop that duplicates what `AlertListener`
  already does.
- **Postgres `LISTEN`/`NOTIFY`.** Postgres is *also* already in the stack, it
  ships native pub/sub with sub-millisecond fanout, and the event we want to
  publish is *the row we just wrote* — so a trigger on the very INSERT that
  creates it is the most direct possible tap. Zero new infrastructure, zero
  changes to `EventsETL.upsert_many` or the poll task.

We chose Postgres. The trigger fires `pg_notify('quake_event_inserts',
row_to_json(NEW)::text)` `AFTER INSERT ... FOR EACH ROW`; the API process owns
one long-lived `LISTEN` connection that decodes each payload into an `EventRow`
and hands it to the in-process registry.

> **INSERT-only by design.** USGS refines magnitude/depth after the first
> report; those arrive as UPDATEs and are observable through
> `quake.event_revisions`. The alert stream is new-events-only (PLAN.md design
> choice 2) — adding "this is a revision of an event you saw earlier" is a
> separate epic if the use case shows up.

> **8000-byte payload limit.** Postgres caps a NOTIFY payload at 8000 bytes.
> An events row sits comfortably under that even with the longest `place`
> string USGS emits, so the whole row travels in the notification — the
> listener never has to round-trip back to the DB to fetch it.

### Listener resilience

`AlertListener` is a supervisor loop, started by the FastAPI lifespan as a
single `asyncio` task and cancelled cleanly on shutdown (`stop()`, then a 10 s
grace period before a hard cancel). Inside the loop:

- The connection is opened in **autocommit** mode — `LISTEN` is meaningless
  inside a transaction in psycopg's default mode.
- If the connection drops, it reconnects with **exponential backoff**
  (1 s → 30 s cap). A `stop()` during backoff exits immediately rather than
  waiting out the sleep.
- The inner consume uses `conn.notifies(timeout=1.0)` rather than a bare
  `async for`. A dormant channel would otherwise block the iterator until the
  *next* NOTIFY ever arrived, making shutdown invisible; the 1 s timeout lets
  the loop notice `stop()` promptly.
- A malformed payload (not JSON, or JSON that isn't an `EventRow` shape) is
  **logged and swallowed**. One bad notification must never take down the
  listener task.

## Filter semantics

A subscriber's filters are a `list[AlertFilterRow]`. Two combination rules,
and they're easy to mix up, so:

- **OR _across_ a key's filters.** An event reaches a subscriber if it matches
  **any one** of their filters. This matches the obvious mental model — adding
  a filter means "*also* alert me on this." Enforced by the registry:
  `any(matches(f, event) for f in sub.filters)`.
- **AND _within_ one filter.** Inside a single filter, **every set predicate**
  must hold. A predicate is "set" when its columns are non-NULL; a NULL column
  means *the operator didn't constrain this dimension, so skip it*. Enforced by
  the matcher.

The three predicates:

| Predicate | Match condition |
|-----------|-----------------|
| `min_magnitude` | `event.magnitude >= filter.min_magnitude` |
| Bounding box | event lat/lon inside the **inclusive** `bbox_min_*` / `bbox_max_*` rectangle |
| Center + radius | great-circle (haversine) distance from `(center_lat, center_lon)` ≤ `radius_km` |

A filter's **shape is bbox XOR center+radius**, optionally combined with a
`min_magnitude` floor. This is enforced application-side by the `AlertFilter`
Pydantic validator (`models/alerts.py`) — a partial bbox, both shapes at once,
or an entirely-empty filter are all rejected with `422`. The DB columns stay
accommodating; the matcher treats bbox and center+radius as independent
predicates that would compose with AND if a hand-built row ever set both.

> **Antimeridian not supported in V1.** A bbox spanning the ±180° meridian
> (`bbox_min_lon > bbox_max_lon`) is rejected by the validator, so the matcher
> can assume ordered bounds. Filters crossing the date line are a future
> enhancement.

### Connect-time snapshot

Filters are read **once, at connect time**, and stored on the subscriber slot.
If a client edits their filters via `/alerts/filters` mid-stream, the open
connection keeps using the **old** snapshot — the change takes effect only when
the client **reconnects**.

This is deliberate (PLAN.md design choice 6): reconnect is the refresh
primitive, which removes the need for a registry-side invalidation channel
that would have to find and mutate live slots. Clients that want fresh filters
applied immediately just drop and reopen the stream.

### On the wire

One event type. Each matched event is sent as:

```
event: alert
data: {"event_id":"us7000abcd","time":"2026-05-20T12:34:56Z","magnitude":5.2,
       "magnitude_type":"mb","depth_km":10.0,"latitude":38.1,"longitude":23.7,
       "place":"12 km NE of Athens","url":"https://earthquake.usgs.gov/..."}
```

The payload is an `AlertEnvelope` — a slim projection of the events row.
Internal timestamps (`inserted_at` / `updated_at`) and revision-only columns
are intentionally omitted. `sse-starlette`'s built-in keep-alive **ping (15 s)**
holds the connection warm between events; there's no custom heartbeat.

> **Empty filter set → 400.** Opening `/alerts/stream` with no filters
> configured returns `400` rather than a stream that could never deliver
> anything. POST a filter to `/alerts/filters` first.

### Back-pressure

Each subscriber owns a **bounded** `asyncio.Queue` (`maxsize=100`). If a slow
client lets its queue fill, the registry **drops the envelope for that slot
only** and logs a warning — it never blocks the fanout for everyone else.
Live alerts beat dead alerts. The stream is purely live (no backfill on
connect); clients use `/events/recent` for the catch-up read.

## Single-pod limit

The `SubscriberRegistry` is an **in-process** singleton. A subscriber's queue
lives in the same process as the SSE connection it feeds. This works because
the deployment is **single-pod by design** (local-only `docker-compose`, one
API container).

> **What breaks at >1 pod.** Each pod runs its own `AlertListener` and its own
> registry. The trigger broadcasts every NOTIFY to *all* listening
> connections, so every pod still sees every event — that part scales fine.
> The limit is subscriber routing: a client connected to pod A is only in pod
> A's registry, and that's exactly the pod that gets the event too, so fanout
> stays correct. The real constraint is **operational visibility**
> (`get_subscriber_count()` is per-pod) and the fact that nothing here has been
> tested under a load balancer.

**Migration path**, if multi-pod is ever in scope: keep the matcher and the
per-pod registry exactly as they are — they're already correct per-pod — and
replace the Postgres NOTIFY tap with a **RabbitMQ fanout exchange** that every
pod's listener binds a queue to. Each pod fans the event into its own local
registry. The in-process matcher never moves; only the cross-process transport
changes. SSE staying in-process is the locked default ([`../CLAUDE.md`](../CLAUDE.md)
§ Design Patterns); this is the escape hatch, not the plan.

## Operator notes

**Confirm the trigger is installed.** In `psql`:

```sql
\df+ quake.events_notify        -- the notify function exists?

-- the trigger is wired to the table?
SELECT tgname, tgenabled
FROM   pg_trigger
WHERE  tgrelid = 'quake.events'::regclass
  AND  NOT tgisinternal;
```

You should see `events_notify_trigger` with `tgenabled = 'O'` (enabled).

**Confirm a listener is connected.** The listener logs `AlertListener
connected` with the channel on boot. From the DB side, the LISTEN session
shows up in `pg_stat_activity`:

```sql
SELECT pid, application_name, state, query
FROM   pg_stat_activity
WHERE  query ILIKE 'LISTEN %';
```

**Fire a test NOTIFY without ingesting.** Useful to exercise the
listener → registry path in isolation. The payload must be a valid `EventRow`
shape or the listener logs and skips it:

```sql
SELECT pg_notify('quake_event_inserts', row_to_json(e))
FROM   quake.events e
LIMIT  1;
```

**Live subscriber count.** `SubscriberRegistry.get_subscriber_count()` returns
the number of currently-connected SSE clients in the process — handy from a
debug shell or a future metrics export. It's per-pod (see the single-pod note).

**Manual SSE test with curl.** Issue a key (`make issue-api-key`), POST a
filter, then open the stream. `-N` disables curl's buffering so frames print as
they arrive:

```bash
KEY=qkf_...                       # from make issue-api-key

# register a filter: magnitude ≥ 4.0 anywhere
curl -s -X POST http://localhost:8000/alerts/filters \
     -H "Authorization: Bearer $KEY" \
     -H "Content-Type: application/json" \
     -d '{"min_magnitude": 4.0}'

# open the stream (blocks; Ctrl-C to close)
curl -N http://localhost:8000/alerts/stream \
     -H "Authorization: Bearer $KEY"
```

The connection stays open; you'll see periodic ping comments and an
`event: alert` frame each time a matching event lands. With nothing matching,
you'll just see the keep-alive pings.

## Related

- [`docs/architecture.md`](architecture.md) — the alert path within the wider data flow.
- [`docs/task-scheduler.md`](task-scheduler.md) — the worker poll whose INSERTs this stream reacts to.
- [`docs/frontend.md`](frontend.md) — the browser-side SSE client (`@microsoft/fetch-event-source`).
