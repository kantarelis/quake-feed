"""Session-scoped sandbox database for ETL tests.

A single ``timescale/timescaledb:latest-pg18`` container is started once
per pytest session on host port 5435, migrated with the project's dbmate
baseline, and torn down at session end. Every test runs against this
container; per-test isolation is provided by a TRUNCATE-everything
fixture that fires before each test.

Tests skip cleanly if Docker is unavailable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

_CONTAINER_NAME = "quake_test_db"
_HOST_PORT = "5435"
_DB_IMAGE = "timescale/timescaledb:latest-pg18"
_DBMATE_IMAGE = "amacneil/dbmate:latest"
_DB_USER = "quake"
_DB_PASS = "quake"
_DB_NAME = "quake-db"

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


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(cmd, check=check, capture_output=True)


def _wait_ready(container: str, *, timeout_s: int = 60) -> None:
    """Poll pg_isready over TCP until the container accepts connections.

    Forces ``-h 127.0.0.1`` so the check goes through the TCP listener, not
    the local socket — TimescaleDB's entrypoint starts a transient local-
    socket-only postgres during initdb that would otherwise produce a
    false-positive ready (same bug fixed in `make migrate-test`).
    """
    for _ in range(timeout_s):
        r = _run(
            ["docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", _DB_USER, "-d", _DB_NAME],
            check=False,
        )
        if r.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError(f"{container} never became ready within {timeout_s}s")


def _set_env_for_sandbox() -> None:
    """Populate every env var the strict loader requires, pointing the DB at the sandbox.

    Defaults are set for non-DB vars so bare ``pytest`` works without sourcing ``.env``;
    DB host/port are *always* overridden so even an externally-set ``.env`` cannot
    accidentally route tests at the compose DB or production.
    """
    os.environ["DB_HOST"] = "127.0.0.1"
    os.environ["DB_PORT"] = _HOST_PORT
    os.environ["DB_USERNAME"] = _DB_USER
    os.environ["DB_PASSWORD"] = _DB_PASS
    os.environ["DB_NAME"] = _DB_NAME
    # Strict loader requires these; values are unused by the ETL layer.
    placeholders = {
        "ENVIRONMENT": "testing",
        "APPLICATION_NAME": "quake-feed-test",
        "QUAKE_HOST_IP": "127.0.0.1",
        "QUAKE_BIND_PORT": "0",
        "LOGGER_NAME": "test",
        "LOGGER_LOG_LEVEL": "10",
        "LOKI_HOST": "127.0.0.1",
        "LOKI_PORT": "0",
        "PROMETHEUS_HOST": "127.0.0.1",
        "PROMETHEUS_PORT": "0",
        "GRAFANA_HOST": "127.0.0.1",
        "GRAFANA_PORT": "0",
        "GF_SECURITY_ADMIN_USER": "x",
        "GF_SECURITY_ADMIN_PASSWORD": "x",
        "RABBITMQ_HOST": "127.0.0.1",
        "RABBITMQ_USERNAME": "x",
        "RABBITMQ_PASSWORD": "x",
        "RABBITMQ_AMQP_PORT": "0",
        "RABBITMQ_MANAGEMENT_PORT": "0",
        "VAULT_HOST": "127.0.0.1",
        "VAULT_PORT": "0",
        "VAULT_DEV_ROOT_TOKEN_ID": "x",
    }
    for k, v in placeholders.items():
        os.environ.setdefault(k, v)


def _apply_migrations() -> None:
    """Run `dbmate up` against the sandbox via the same Docker image the Makefile uses."""
    cwd = Path.cwd().resolve()
    url = f"postgres://{_DB_USER}:{_DB_PASS}@127.0.0.1:{_HOST_PORT}/{_DB_NAME}?sslmode=disable"
    _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "host",
            "-v",
            f"{cwd}/database:/db:rw",
            "-w",
            "/db",
            "-e",
            f"DATABASE_URL={url}",
            _DBMATE_IMAGE,
            "--migrations-dir",
            "/db/migrations",
            "--migrations-table",
            "public.schema_migrations",
            "--no-dump-schema",
            "up",
        ]
    )


@pytest.fixture(scope="session", autouse=True)
def _test_db() -> Iterator[None]:
    """Start the sandbox DB once per session, migrate it, tear it down at exit."""
    if not _docker_available():
        pytest.skip("docker not available; ETL tests require a sandbox DB", allow_module_level=False)

    _set_env_for_sandbox()

    # Kill any stale container from a previously-aborted run, then start fresh.
    _run(["docker", "rm", "-f", _CONTAINER_NAME], check=False)
    _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            _CONTAINER_NAME,
            "-e",
            f"POSTGRES_USER={_DB_USER}",
            "-e",
            f"POSTGRES_PASSWORD={_DB_PASS}",
            "-e",
            f"POSTGRES_DB={_DB_NAME}",
            "-p",
            f"{_HOST_PORT}:5432",
            _DB_IMAGE,
        ]
    )

    try:
        _wait_ready(_CONTAINER_NAME)
        _apply_migrations()

        # Clear the env-var cache so the pool, when first built, sees the sandbox config.
        from functions.environment import get_environmental_variables

        get_environmental_variables.cache_clear()

        yield
    finally:
        # Close the pool before tearing down the container, otherwise atexit
        # tries to close it against a dead host and emits a warning.
        from database.main import _close_pool

        _close_pool()
        _run(["docker", "rm", "-f", _CONTAINER_NAME], check=False)


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    """TRUNCATE every quake.* table before each test, then re-seed INGESTION_LOCK."""
    from database.main import transaction

    with transaction() as conn:
        conn.execute(_TRUNCATE_SQL)
        conn.execute(_SEED_INGESTION_LOCK_SQL)
    yield
