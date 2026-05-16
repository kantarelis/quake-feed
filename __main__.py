"""Application entrypoint.

Run with ``python __main__.py`` (or ``python -m`` from the repo root).
Loads env, configures structured logging, pings Vault for visibility, and
hands control to the ``Quake`` FastAPI app.
"""

from __future__ import annotations

from functions.environment import get_environmental_variables
from functions.logger import setup_logger
from functions.vault import init_vault
from quake.main import Quake


def main() -> None:
    env = get_environmental_variables()
    logger = setup_logger(
        name=env.logger.name,
        app_name=env.application_name,
        level=env.logger.log_level,
    )
    init_vault(logger)
    quake = Quake(logger=logger)
    quake.run(host=env.backend.host, port=env.backend.port)


if __name__ == "__main__":
    main()
