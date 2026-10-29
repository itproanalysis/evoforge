"""Critic — v3.6 ENG-02 / AT-20: an opened PR is not a verified improvement, and the dashboard says why WVI is 0."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def test_opened_pr_counts_as_awaiting_not_validated(monkeypatch):
    missions = [
        {"mission_id": "m_pr", "state": "PR_OPENED", "stages": {}},
        {"mission_id": "m_done", "state": "PR_OPENED", "stages": {}},
        {"mission_id": "m_new", "state": "CREATED", "stages": {}},
    ]
    monkeypatch.setattr(main.missions_store, "all", lambda: missions)
    monkeypatch.setattr(main, "_all_validated", lambda: [{"mission_id": "m_done"}])
    d = c.get("/v1/dashboard").json()
    assert d["validated_improvements"] == 1
    assert d["prs_awaiting_validation"] == 1
    assert "does not count" in d["wvi_rule"]
    assert d["spend_basis"] == "model_api_usage"


def test_mission_control_shows_awaiting_tile_and_rule_in_both_locales():
    page = (WEB / "app" / "[locale]" / "page.tsx").read_text(encoding="utf-8")
    assert "prs_awaiting_validation" in page and 'metrics.wvi-rule' in page
    for lang in ("en", "ko"):
        m = json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))
        found = [v for v in m.values() if isinstance(v, dict) and isinstance(v.get("metrics"), dict)
                 and "prs-awaiting" in v["metrics"]]
        found += [m["metrics"]] if isinstance(m.get("metrics"), dict) and "prs-awaiting" in m["metrics"] else []
        assert found, lang
        metrics = found[0]["metrics"] if "metrics" in found[0] else found[0]
        assert metrics["wvi-rule"] and metrics["spent"] not in ("Spent", "실제 지출")
