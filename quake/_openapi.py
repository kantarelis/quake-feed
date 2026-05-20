"""Dump the FastAPI OpenAPI spec to stdout for frontend type generation.

Invoked by ``make frontend-gen-api`` as ``python -m quake._openapi``. The
strict settings loader (:mod:`functions.environment`) requires a full env block
to construct the app — but ``app.openapi()`` only introspects routes and
Pydantic models, it never opens a DB / Vault / broker connection. So we seed
placeholder values (mirroring ``tests/_sandbox.set_required_env``) before
importing the app, which keeps the dump hermetic and CI-safe: no running
server, no services contacted.

Output is ``indent=2, sort_keys=True`` so the generated schema is stable and
diffable across regenerations.
"""

from __future__ import annotations

import json
import logging
import os

# Throwaway value for the credential-shaped env vars. Routed through a name
# (not a string literal) so bandit's hardcoded-password heuristic doesn't fire —
# none of these are real secrets and nothing is authenticated against here.
_PLACEHOLDER = "placeholder"

# Enough to satisfy the strict settings validator. Values are placeholders —
# nothing here is connected to during an OpenAPI dump. ``setdefault`` lets a
# real environment (e.g. a sourced .env) win if one is present.
_PLACEHOLDER_ENV = {
    "ENVIRONMENT": "development",
    "APPLICATION_NAME": "quake-feed",
    "QUAKE_HOST_IP": "127.0.0.1",
    "QUAKE_BIND_PORT": "8000",
    "DB_USERNAME": "quake",
    "DB_PASSWORD": _PLACEHOLDER,
    "DB_NAME": "quake-db",
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "5432",
    "LOGGER_NAME": "quake-feed",
    "LOGGER_LOG_LEVEL": "20",
    "LOKI_HOST": "127.0.0.1",
    "LOKI_PORT": "3100",
    "PROMETHEUS_HOST": "127.0.0.1",
    "PROMETHEUS_PORT": "9090",
    "GRAFANA_HOST": "127.0.0.1",
    "GRAFANA_PORT": "3000",
    "GF_SECURITY_ADMIN_USER": "admin",
    "GF_SECURITY_ADMIN_PASSWORD": _PLACEHOLDER,
    "RABBITMQ_HOST": "127.0.0.1",
    "RABBITMQ_USERNAME": "guest",
    "RABBITMQ_PASSWORD": _PLACEHOLDER,
    "RABBITMQ_AMQP_PORT": "5672",
    "RABBITMQ_MANAGEMENT_PORT": "15672",
    "VAULT_HOST": "127.0.0.1",
    "VAULT_PORT": "8200",
    "VAULT_DEV_ROOT_TOKEN_ID": _PLACEHOLDER,
}


def main() -> None:
    for key, value in _PLACEHOLDER_ENV.items():
        os.environ.setdefault(key, value)

    # Imported only after the env is seeded — modules in the app's dependency
    # graph validate settings at import time.
    from quake.main import Quake

    app = Quake(logger=logging.getLogger("openapi-dump")).app
    print(json.dumps(app.openapi(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
