"""Environment-variable loading and validation.

The model is a plain ``BaseModel``; ``get_environmental_variables()`` reads
``os.environ`` into a nested dict and feeds it to ``model_validate``. This
keeps validation runtime-enforced (missing env vars raise) while making the
env-reading step explicit and statically typeable.

``.env`` loading is the caller's responsibility — the Makefile sources it for
local commands, and ``docker-compose`` injects it via ``env_file:``.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from typing import Any

from pydantic import BaseModel


class Environment(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class BackendConfig(BaseModel):
    host: str
    port: int


class WorkerConfig(BaseModel):
    metrics_port: int


class DatabaseConfig(BaseModel):
    username: str
    password: str
    name: str
    host: str
    port: int


class LoggerConfig(BaseModel):
    name: str
    log_level: int
    loki_host: str
    loki_port: int


class PrometheusConfig(BaseModel):
    host: str
    port: int


class GrafanaConfig(BaseModel):
    host: str
    port: int
    admin_user: str
    admin_password: str


class RabbitMQConfig(BaseModel):
    host: str
    username: str
    password: str
    amqp_port: int
    management_port: int


class VaultConfig(BaseModel):
    host: str
    port: int
    dev_root_token_id: str
    unseal_keys: str = ""
    token: str = ""

    @property
    def address(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def unseal_keys_list(self) -> list[str]:
        return [k.strip() for k in self.unseal_keys.split(",") if k.strip()]


class EnvironmentalVariables(BaseModel):
    environment: Environment
    application_name: str
    backend: BackendConfig
    worker: WorkerConfig
    database: DatabaseConfig
    logger: LoggerConfig
    prometheus: PrometheusConfig
    grafana: GrafanaConfig
    rabbitmq: RabbitMQConfig
    vault: VaultConfig


def _require(key: str) -> str:
    """Read an env var, raising ``KeyError`` with a clear message if missing."""
    try:
        return os.environ[key]
    except KeyError as exc:
        raise KeyError(f"Required environment variable {key} is not set") from exc


def _load_from_env() -> dict[str, Any]:
    """Read every env var the app needs into a nested dict shaped like the model."""
    return {
        "environment": _require("ENVIRONMENT"),
        "application_name": _require("APPLICATION_NAME"),
        "backend": {
            "host": _require("QUAKE_HOST_IP"),
            "port": _require("QUAKE_BIND_PORT"),
        },
        "worker": {
            # Optional with a default so the API/test envs need not set it; the
            # worker's Prometheus exporter binds this port (see prometheus.yml).
            "metrics_port": os.environ.get("WORKER_METRICS_PORT", "8001"),
        },
        "database": {
            "username": _require("DB_USERNAME"),
            "password": _require("DB_PASSWORD"),
            "name": _require("DB_NAME"),
            "host": _require("DB_HOST"),
            "port": _require("DB_PORT"),
        },
        "logger": {
            "name": _require("LOGGER_NAME"),
            "log_level": _require("LOGGER_LOG_LEVEL"),
            "loki_host": _require("LOKI_HOST"),
            "loki_port": _require("LOKI_PORT"),
        },
        "prometheus": {
            "host": _require("PROMETHEUS_HOST"),
            "port": _require("PROMETHEUS_PORT"),
        },
        "grafana": {
            "host": _require("GRAFANA_HOST"),
            "port": _require("GRAFANA_PORT"),
            "admin_user": _require("GF_SECURITY_ADMIN_USER"),
            "admin_password": _require("GF_SECURITY_ADMIN_PASSWORD"),
        },
        "rabbitmq": {
            "host": _require("RABBITMQ_HOST"),
            "username": _require("RABBITMQ_USERNAME"),
            "password": _require("RABBITMQ_PASSWORD"),
            "amqp_port": _require("RABBITMQ_AMQP_PORT"),
            "management_port": _require("RABBITMQ_MANAGEMENT_PORT"),
        },
        "vault": {
            "host": _require("VAULT_HOST"),
            "port": _require("VAULT_PORT"),
            "dev_root_token_id": _require("VAULT_DEV_ROOT_TOKEN_ID"),
            "unseal_keys": os.environ.get("VAULT_UNSEAL_KEYS", ""),
            "token": os.environ.get("VAULT_TOKEN", ""),
        },
    }


@lru_cache(maxsize=1)
def get_environmental_variables() -> EnvironmentalVariables:
    return EnvironmentalVariables.model_validate(_load_from_env())
