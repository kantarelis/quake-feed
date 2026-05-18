"""Unit tests for :mod:`quake.tasks`.

The tasks' bodies are kept trivial — they delegate to ``poll_once`` and a
plain ``SELECT 1`` — so the meaningful behaviour is already covered by
``test_ingest.py`` and the ``transaction()`` plumbing. These tests pin:

* That both tasks register under their expected names so Celery's worker
  (started as ``celery -A config.celery_app worker``) can find them.
* That invoking each task synchronously through Celery's registry
  produces the documented return shape.

``apply()`` runs the task locally without going through RabbitMQ. We look
the task up through ``celery_app.tasks[name]`` instead of importing the
decorated symbol directly so the type checker sees a ``Task`` (the
``@celery_app.task`` decorator's return type is opaque to pyright).
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from config import celery_app
from quake.ingestion.usgs.client import UsgsClient

# Side-effect import: runs the @celery_app.task decorators in quake/tasks.py.
# ``include=["quake.tasks"]`` on the Celery app only fires inside the worker
# boot path; in tests we register them explicitly.
importlib.import_module("quake.tasks")

_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "usgs_all_hour.json"
_POLL_NAME = "quake.tasks.poll_usgs"
_HEALTH_NAME = "quake.tasks.health_check"


@pytest.fixture
def fixture_dict() -> dict[str, Any]:
    return json.loads(_FIXTURE_PATH.read_text())


@pytest.fixture
def patch_fetch(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, Any]], None]:
    def _patch(payload: dict[str, Any]) -> None:
        def _fake_fetch(self: UsgsClient, feed: Any) -> dict[str, Any]:
            return payload

        monkeypatch.setattr(UsgsClient, "fetch", _fake_fetch)

    return _patch


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def test_tasks_are_registered_under_expected_names() -> None:
    assert _POLL_NAME in celery_app.tasks
    assert _HEALTH_NAME in celery_app.tasks


# ---------------------------------------------------------------------------
# poll_usgs
# ---------------------------------------------------------------------------


def test_poll_usgs_returns_ingestion_result_dict(
    fixture_dict: dict[str, Any],
    patch_fetch: Callable[[dict[str, Any]], None],
) -> None:
    patch_fetch(fixture_dict)

    payload = celery_app.tasks[_POLL_NAME].apply().get()

    feature_count = len(fixture_dict["features"])
    assert payload == {
        "inserted": feature_count,
        "updated": 0,
        "revisions": 0,
        "error": None,
    }


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


def test_health_check_returns_ok_envelope() -> None:
    payload = celery_app.tasks[_HEALTH_NAME].apply().get()

    assert payload["status"] == "ok"
    assert "ts" in payload
    parsed = datetime.fromisoformat(payload["ts"])
    assert parsed.tzinfo is not None
