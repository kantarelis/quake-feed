-- migrate:up

-- ===========================================================================
-- pg_notify trigger on quake.events INSERT.
-- Fires one NOTIFY per inserted row on the 'quake_event_inserts' channel
-- carrying the inserted row encoded as JSON. The API process's
-- AlertListener (quake/alerts/listener.py) LISTENs on this channel and
-- bridges each notify into the in-process SubscriberRegistry.
--
-- INSERT-only by design (Epic 6 / PLAN.md design choice 2). USGS magnitude
-- and depth refinements arrive as UPDATEs; those are observable through
-- quake.event_revisions and out of scope for the V1 alerts stream.
--
-- NOTIFY payload size limit is 8000 bytes; an events row sits comfortably
-- under that even with the longest place strings USGS emits.
-- ===========================================================================

CREATE OR REPLACE FUNCTION quake.events_notify()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_notify('quake_event_inserts', row_to_json(NEW)::text);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS events_notify_trigger ON quake.events;
CREATE TRIGGER events_notify_trigger
    AFTER INSERT ON quake.events
    FOR EACH ROW
    EXECUTE FUNCTION quake.events_notify();


-- migrate:down

DROP TRIGGER IF EXISTS events_notify_trigger ON quake.events;
DROP FUNCTION IF EXISTS quake.events_notify();
