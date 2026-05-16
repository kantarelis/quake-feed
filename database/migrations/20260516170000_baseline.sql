-- migrate:up

-- ===========================================================================
-- Extensions and schema
-- ===========================================================================
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE SCHEMA IF NOT EXISTS quake;

-- ===========================================================================
-- quake.events — TimescaleDB hypertable.
-- One row per (event_id, time). The application UPSERTs on the composite PK.
-- USGS rarely revises an event's `time`; if it does, both rows coexist and
-- consumers select the freshest with `ORDER BY time DESC LIMIT 1`.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quake.events (
    event_id       TEXT             NOT NULL,
    time           TIMESTAMPTZ      NOT NULL,
    magnitude      DOUBLE PRECISION NOT NULL,
    magnitude_type TEXT,
    depth_km       DOUBLE PRECISION,
    latitude       DOUBLE PRECISION NOT NULL,
    longitude      DOUBLE PRECISION NOT NULL,
    place          TEXT,
    status         TEXT,
    tsunami        BOOLEAN          NOT NULL DEFAULT FALSE,
    url            TEXT,
    inserted_at    TIMESTAMPTZ      NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, time)
);

SELECT create_hypertable('quake.events', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS events_magnitude_idx ON quake.events (magnitude);
CREATE INDEX IF NOT EXISTS events_lat_lon_idx   ON quake.events (latitude, longitude);

-- ===========================================================================
-- quake.event_revisions — append-only audit log written by trigger.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quake.event_revisions (
    id             BIGSERIAL        PRIMARY KEY,
    event_id       TEXT             NOT NULL,
    observed_at    TIMESTAMPTZ      NOT NULL DEFAULT now(),
    old_magnitude  DOUBLE PRECISION,
    new_magnitude  DOUBLE PRECISION,
    old_depth_km   DOUBLE PRECISION,
    new_depth_km   DOUBLE PRECISION,
    old_place      TEXT,
    new_place      TEXT
);

CREATE INDEX IF NOT EXISTS event_revisions_event_observed_idx
    ON quake.event_revisions (event_id, observed_at DESC);

-- ===========================================================================
-- quake.api_keys — hash-only registry. Raw keys live in Vault.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quake.api_keys (
    id           BIGSERIAL    PRIMARY KEY,
    key_hash     TEXT         NOT NULL UNIQUE,
    label        TEXT,
    scopes       TEXT[]       NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ
);

-- ===========================================================================
-- quake.alert_filters — per-API-key persistent filter sets.
-- Filter shape (bbox XOR center+radius) is enforced application-side;
-- the table accepts both bbox and center+radius columns and the matcher
-- decides which set to use per row.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quake.alert_filters (
    id            BIGSERIAL        PRIMARY KEY,
    api_key_id    BIGINT           NOT NULL
                                   REFERENCES quake.api_keys(id) ON DELETE CASCADE,
    min_magnitude DOUBLE PRECISION,
    bbox_min_lat  DOUBLE PRECISION,
    bbox_min_lon  DOUBLE PRECISION,
    bbox_max_lat  DOUBLE PRECISION,
    bbox_max_lon  DOUBLE PRECISION,
    center_lat    DOUBLE PRECISION,
    center_lon    DOUBLE PRECISION,
    radius_km     DOUBLE PRECISION,
    created_at    TIMESTAMPTZ      NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ      NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS alert_filters_api_key_idx
    ON quake.alert_filters (api_key_id);

-- ===========================================================================
-- quake.endpoint_locks — runtime kill-switch flags.
-- INGESTION_LOCK is pre-seeded so the admin endpoint (Epic 5) can flip it
-- without having to first INSERT.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quake.endpoint_locks (
    lock_name TEXT        PRIMARY KEY,
    is_locked BOOLEAN     NOT NULL DEFAULT FALSE,
    locked_by TEXT,
    locked_at TIMESTAMPTZ,
    reason    TEXT
);

INSERT INTO quake.endpoint_locks (lock_name)
VALUES ('INGESTION_LOCK')
ON CONFLICT (lock_name) DO NOTHING;

-- ===========================================================================
-- quake.ingestion_runs — per-poll observability log.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quake.ingestion_runs (
    id              BIGSERIAL    PRIMARY KEY,
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    inserted_count  INTEGER      NOT NULL DEFAULT 0,
    updated_count   INTEGER      NOT NULL DEFAULT 0,
    revision_count  INTEGER      NOT NULL DEFAULT 0,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS ingestion_runs_started_idx
    ON quake.ingestion_runs (started_at DESC);

-- ===========================================================================
-- Revision trigger.
-- Writes one quake.event_revisions row when an UPDATE on quake.events
-- crosses any of these thresholds:
--   |Δ magnitude|  >= 0.1
--   |Δ depth_km|   >= 1.0
--   place changed (any non-equal text)
-- Thresholds are inlined here per CLAUDE.md ("defined in a migration").
-- ===========================================================================
CREATE OR REPLACE FUNCTION quake.events_record_revision()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF
        (NEW.magnitude IS DISTINCT FROM OLD.magnitude
         AND abs(NEW.magnitude - OLD.magnitude) >= 0.1)
        OR
        (NEW.depth_km IS DISTINCT FROM OLD.depth_km
         AND COALESCE(abs(NEW.depth_km - OLD.depth_km), 0) >= 1.0)
        OR
        (NEW.place IS DISTINCT FROM OLD.place)
    THEN
        INSERT INTO quake.event_revisions (
            event_id, observed_at,
            old_magnitude, new_magnitude,
            old_depth_km,  new_depth_km,
            old_place,     new_place
        )
        VALUES (
            NEW.event_id, now(),
            OLD.magnitude, NEW.magnitude,
            OLD.depth_km,  NEW.depth_km,
            OLD.place,     NEW.place
        );
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS events_revision_trigger ON quake.events;
CREATE TRIGGER events_revision_trigger
    AFTER UPDATE ON quake.events
    FOR EACH ROW
    EXECUTE FUNCTION quake.events_record_revision();


-- migrate:down

DROP TRIGGER IF EXISTS events_revision_trigger ON quake.events;
DROP FUNCTION IF EXISTS quake.events_record_revision();
DROP TABLE IF EXISTS quake.ingestion_runs;
DROP TABLE IF EXISTS quake.endpoint_locks;
DROP TABLE IF EXISTS quake.alert_filters;
DROP TABLE IF EXISTS quake.api_keys;
DROP TABLE IF EXISTS quake.event_revisions;
DROP TABLE IF EXISTS quake.events;
DROP SCHEMA IF EXISTS quake CASCADE;
