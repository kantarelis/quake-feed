"""Celery Beat schedule helpers."""

from __future__ import annotations

import os

from celery.schedules import crontab


def crontab_or_default(env_var: str, default: str) -> crontab:
    """Read a 5-field cron string from env and return a Celery ``crontab``.

    Falls back to ``default`` when the env var is unset or empty. Raises
    ``ValueError`` if the expression does not have exactly five fields.
    """
    expression = os.environ.get(env_var, "").strip() or default
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError(
            f"Invalid crontab expression for {env_var}: {expression!r} " f"(expected 5 fields, got {len(parts)})"
        )
    minute, hour, day_of_month, month_of_year, day_of_week = parts
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )
