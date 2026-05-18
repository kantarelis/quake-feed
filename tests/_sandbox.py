"""Shared docker-backed sandbox-DB helpers for both unit and integration tests.

Both ``tests/unit/conftest.py`` and ``tests/integration/conftest.py`` use
this module to bring up a clean TimescaleDB container, apply migrations,
and tear it down at session end. The two suites pass different
``container_name`` / ``host_port`` so they can coexist (e.g., if the unit
sandbox is still running when integration tests are invoked).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

DB_IMAGE = "timescale/timescaledb:latest-pg18"
DBMATE_IMAGE = "amacneil/dbmate:latest"
DB_USER = "quake"
DB_PASS = "quake"
DB_NAME = "quake-db"


def docker_available() -> bool:
    return shutil.which("docker") is not None


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(cmd, check=check, capture_output=True)


def wait_ready(container: str, *, timeout_s: int = 60) -> None:
    """Poll ``pg_isready`` over TCP until the container accepts connections.

    Forces ``-h 127.0.0.1`` so the check goes through the TCP listener, not
    the local socket — TimescaleDB's entrypoint starts a transient local-
    socket-only postgres during initdb that would otherwise produce a
    false-positive ready (same bug fixed in ``make migrate-test``).
    """
    for _ in range(timeout_s):
        r = _run(
            ["docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", DB_USER, "-d", DB_NAME],
            check=False,
        )
        if r.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError(f"{container} never became ready within {timeout_s}s")


def set_required_env(host_port: str) -> None:
    """Populate every env var the strict loader requires, pointing the DB at the sandbox.

    DB host/port are *always* overridden so even an externally-set ``.env``
    cannot accidentally route tests at the compose DB or production. Other
    placeholders use ``setdefault`` so a user-provided value wins.
    """
    os.environ["DB_HOST"] = "127.0.0.1"
    os.environ["DB_PORT"] = host_port
    os.environ["DB_USERNAME"] = DB_USER
    os.environ["DB_PASSWORD"] = DB_PASS
    os.environ["DB_NAME"] = DB_NAME
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


def apply_migrations(host_port: str) -> None:
    """Run ``dbmate up`` against the sandbox via the same Docker image the Makefile uses."""
    cwd = Path.cwd().resolve()
    url = f"postgres://{DB_USER}:{DB_PASS}@127.0.0.1:{host_port}/{DB_NAME}?sslmode=disable"
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
            DBMATE_IMAGE,
            "--migrations-dir",
            "/db/migrations",
            "--migrations-table",
            "public.schema_migrations",
            "--no-dump-schema",
            "up",
        ]
    )


def start_container(container_name: str, host_port: str) -> None:
    """Kill any stale container with this name, then boot a fresh TimescaleDB."""
    _run(["docker", "rm", "-f", container_name], check=False)
    _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-e",
            f"POSTGRES_USER={DB_USER}",
            "-e",
            f"POSTGRES_PASSWORD={DB_PASS}",
            "-e",
            f"POSTGRES_DB={DB_NAME}",
            "-p",
            f"{host_port}:5432",
            DB_IMAGE,
        ]
    )


def stop_container(container_name: str) -> None:
    _run(["docker", "rm", "-f", container_name], check=False)
