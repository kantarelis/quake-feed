"""Structured-logging setup.

Emits JSON to stdout. Shipping to Loki is handled at the container layer
(promtail tailing the docker log driver), so there is no in-process Loki
push handler here. Epic 8 wires the container-side collection.
"""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger.json import JsonFormatter

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_HANDLER_MARKER = "_quake_handler"


def setup_logger(name: str, app_name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a logger that emits JSON to stdout, with ``app`` set on every record.

    Idempotent: calling twice with the same ``name`` returns the same logger
    without duplicating handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if any(getattr(h, _HANDLER_MARKER, False) for h in logger.handlers):
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(
        JsonFormatter(
            _LOG_FORMAT,
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
            static_fields={"app": app_name},
        )
    )
    setattr(handler, _HANDLER_MARKER, True)
    logger.addHandler(handler)

    logger.propagate = False
    return logger
