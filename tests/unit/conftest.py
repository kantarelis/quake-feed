"""Session-scoped sandbox database for unit tests.

A single ``timescale/timescaledb:latest-pg18`` container is started once
per pytest session on host port 5435, migrated with the project's dbmate
baseline, and torn down at session end. Every unit test runs against this
container; per-test isolation is provided by a TRUNCATE-everything
fixture that fires before each test.

Tests skip cleanly if Docker is unavailable. Helpers are shared with
``tests/integration/conftest.py`` via :mod:`tests._sandbox` — that suite
brings up its own container on a different port so the two can coexist.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests import _sandbox

_CONTAINER_NAME = "quake_test_db"
_HOST_PORT = "5435"

_TRUNCATE_SQL = """
    TRUNCATE
        quake.events,
        quake.event_revisions,
        quake.api_keys,
        quake.alert_filters,
        quake.ingestion_runs,
        quake.endpoint_locks
    RESTART IDENTITY CASCADE
"""

_SEED_INGESTION_LOCK_SQL = """
    INSERT INTO quake.endpoint_locks (lock_name)
    VALUES ('INGESTION_LOCK')
    ON CONFLICT (lock_name) DO NOTHING
"""

# Populate sandbox env vars at conftest import time so test modules whose
# imports eagerly read env (notably ``config.py``, pulled in by
# ``quake.tasks``) can be collected before the session fixture runs.
_sandbox.set_required_env(_HOST_PORT)


@pytest.fixture(scope="session", autouse=True)
def _test_db() -> Iterator[None]:
    """Start the sandbox DB once per session, migrate it, tear it down at exit."""
    if not _sandbox.docker_available():
        pytest.skip("docker not available; ETL tests require a sandbox DB", allow_module_level=False)

    _sandbox.set_required_env(_HOST_PORT)
    _sandbox.start_container(_CONTAINER_NAME, _HOST_PORT)

    try:
        _sandbox.wait_ready(_CONTAINER_NAME)
        _sandbox.apply_migrations(_HOST_PORT)

        # Clear the env-var cache so the pool, when first built, sees the sandbox config.
        from functions.environment import get_environmental_variables

        get_environmental_variables.cache_clear()

        yield
    finally:
        # Close the pool before tearing down the container, otherwise atexit
        # tries to close it against a dead host and emits a warning.
        from database.main import _close_pool

        _close_pool()
        _sandbox.stop_container(_CONTAINER_NAME)


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    """TRUNCATE every quake.* table before each test, then re-seed INGESTION_LOCK."""
    from database.main import transaction

    with transaction() as conn:
        conn.execute(_TRUNCATE_SQL)
        conn.execute(_SEED_INGESTION_LOCK_SQL)
    yield
