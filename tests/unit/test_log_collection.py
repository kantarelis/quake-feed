"""Guards the promtail → Loki log-collection config against drift.

The dashboard's logs panel queries ``{job="quake-feed"}``; promtail is what
stamps that label onto the app streams. These tests assert the config parses,
pushes to Loki, sets the expected ``job`` label, and that the label still
matches the dashboard query — so renaming the label on one side fails CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent.parent
_PROMTAIL = _ROOT / "monitoring" / "promtail-config.yml"
_DASHBOARD = _ROOT / "monitoring" / "grafana" / "dashboards" / "ingestion.json"

_JOB = "quake-feed"


def test_promtail_config_parses_and_pushes_to_loki() -> None:
    cfg = yaml.safe_load(_PROMTAIL.read_text())
    urls = [client["url"] for client in cfg["clients"]]
    assert any("loki:3100" in url for url in urls), urls


def test_promtail_stamps_the_job_label() -> None:
    cfg = yaml.safe_load(_PROMTAIL.read_text())
    relabels = cfg["scrape_configs"][0]["relabel_configs"]
    job_rules = [r for r in relabels if r.get("target_label") == "job" and r.get("replacement") == _JOB]
    assert job_rules, f"promtail must set job={_JOB!r} via a relabel replacement"


def test_dashboard_loki_query_matches_promtail_job_label() -> None:
    dashboard = json.loads(_DASHBOARD.read_text())
    loki_panels = [p for p in dashboard["panels"] if p.get("datasource") == "Loki"]
    assert loki_panels, "dashboard has no Loki panel"
    for panel in loki_panels:
        for target in panel["targets"]:
            assert f'job="{_JOB}"' in target["expr"], target["expr"]
