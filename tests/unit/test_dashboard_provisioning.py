"""Guards the provisioned Grafana ingestion dashboard against drift.

The dashboard is checked-in JSON discovered by the file provider; its panels
reference the provisioned datasources by name. These tests assert the JSON
parses, carries the expected panels, and that every datasource it names is
actually declared in ``provisioning/datasources/datasources.yml`` — so renaming
or dropping a datasource without updating the dashboard fails CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent.parent
_DASHBOARD = _ROOT / "monitoring" / "grafana" / "dashboards" / "ingestion.json"
_DATASOURCES = _ROOT / "monitoring" / "grafana" / "provisioning" / "datasources" / "datasources.yml"

_EXPECTED_PANEL_TITLES = {
    "Poll rate & errors",
    "Poll duration (p50 / p95)",
    "Event ingest rate (inserted / updated / revisions)",
    "Active SSE connections",
    "Application logs",
}


def _load_dashboard() -> dict[str, Any]:
    return json.loads(_DASHBOARD.read_text())


def _provisioned_datasource_names() -> set[str]:
    data = yaml.safe_load(_DATASOURCES.read_text())
    return {ds["name"] for ds in data["datasources"]}


def test_dashboard_is_valid_json_with_panels() -> None:
    dashboard = _load_dashboard()
    assert dashboard.get("uid"), "dashboard needs a stable uid"
    assert isinstance(dashboard.get("panels"), list)
    assert dashboard["panels"], "dashboard declares no panels"


def test_expected_panels_present() -> None:
    titles = {panel["title"] for panel in _load_dashboard()["panels"]}
    missing = _EXPECTED_PANEL_TITLES - titles
    assert not missing, f"missing panels: {missing}"


def test_every_datasource_reference_is_provisioned() -> None:
    """Panel- and target-level datasource names must all be declared in datasources.yml."""
    names = _provisioned_datasource_names()
    assert {"Prometheus", "Loki"} <= names  # sanity: the names this dashboard relies on

    for panel in _load_dashboard()["panels"]:
        panel_ds = panel.get("datasource")
        assert panel_ds in names, f"panel {panel.get('title')!r} datasource {panel_ds!r} not provisioned"
        for target in panel.get("targets", []):
            target_ds = target.get("datasource")
            assert target_ds in names, f"panel {panel.get('title')!r} target datasource {target_ds!r} not provisioned"
