"""Session-scoped sandbox database for integration tests.

Integration tests own their dependencies: they spin up their own
TimescaleDB container on host port 5436, apply the project's migrations,
run, and tear down. The compose stack does **not** need to be up — the
only external dependencies are Docker (for the DB) and outbound HTTPS
(for real USGS).

Uses a different container name + port than the unit sandbox so both can
coexist; helpers are shared via :mod:`tests._sandbox`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests import _sandbox

_CONTAINER_NAME = "quake_test_integration_db"
_HOST_PORT = "5436"

# Populate sandbox env vars at conftest import time so test modules whose
# imports eagerly read env (notably ``config.py``, pulled in by
# ``quake.tasks``) can be collected before the session fixture runs.
_sandbox.set_required_env(_HOST_PORT)


@pytest.fixture(scope="session", autouse=True)
def _test_db() -> Iterator[None]:
    """Start the integration sandbox DB once per session, migrate it, tear it down."""
    if not _sandbox.docker_available():
        pytest.skip("docker not available; integration tests require a sandbox DB", allow_module_level=False)

    _sandbox.set_required_env(_HOST_PORT)
    _sandbox.start_container(_CONTAINER_NAME, _HOST_PORT)

    try:
        _sandbox.wait_ready(_CONTAINER_NAME)
        _sandbox.apply_migrations(_HOST_PORT)

        from functions.environment import get_environmental_variables

        get_environmental_variables.cache_clear()

        yield
    finally:
        from database.main import _close_pool

        _close_pool()
        _sandbox.stop_container(_CONTAINER_NAME)
