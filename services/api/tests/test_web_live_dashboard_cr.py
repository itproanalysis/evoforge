"""Tests for live web dashboard, WVI outcome recording, Lab mission loader, and i18n performance routing."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import commands, ledger, missions, outcomes, performance  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"
c = TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()
    missions.reset()
    outcomes.reset()
    performance.clear()


def test_next_intl_plugin_and_locale_performance_route_configured():
    next_cfg = (WEB / "next.config.ts").read_text(encoding="utf-8")
    assert "createNextIntlPlugin" in next_cfg
    assert "./i18n.ts" in next_cfg

    locale_perf = WEB / "app" / "[locale]" / "performance" / "page.tsx"
    assert locale_perf.is_file()
    assert "PerformancePage" in locale_perf.read_text(encoding="utf-8")

    locale_layout = (WEB / "app" / "[locale]" / "layout.tsx").read_text(encoding="utf-8")
    assert "/performance" in locale_layout
    assert "t('performance')" in locale_layout


def test_mission_control_pages_have_live_missions_outcomes_wvi_and_performance():
    for rel in ("app/page.tsx", "app/[locale]/page.tsx"):
        src = (WEB / rel).read_text(encoding="utf-8")
        for fn in (
            "getDashboard",
            "getLedger",
            "getMission",
            "getPerformance",
            "listMissions",
            "listOutcomes",
            "postOutcome",
        ):
            assert fn in src, (rel, fn)
        assert "validated_improvements" in src, rel
        assert "/performance" in src, rel
        assert "toFixed" not in src and "parseFloat" not in src, rel


def test_lab_and_evidence_pages_integrate_live_server_missions_and_evidence():
    for rel in ("app/lab/page.tsx", "app/[locale]/lab/page.tsx"):
        src = (WEB / rel).read_text(encoding="utf-8")
        assert "listMissions" in src and "getMission" in src, rel
        assert "/evidence?id=" in src, rel

    for rel in ("app/evidence/page.tsx", "app/[locale]/evidence/page.tsx"):
        src = (WEB / rel).read_text(encoding="utf-8")
        assert "listMissions" in src and "listOutcomes" in src, rel
        assert "URLSearchParams" in src, rel
        assert "Review" in src and "/v1/events/" in src, rel


def test_performance_page_preserves_honest_invariants_and_links_evidence():
    perf_src = (WEB / "app" / "performance" / "page.tsx").read_text(encoding="utf-8")
    assert "not_measured" in perf_src and "측정 전" in perf_src
    assert "추정치" not in perf_src and "estimate" not in perf_src.lower()
    assert "getPerformance" in perf_src
    assert "/evidence?id=" in perf_src
    assert not re.search(r"pass_?rate\s*[:=]\s*\d", perf_src)


def test_live_dashboard_endpoints_roundtrip():
    r_create = c.post(
        "/v1/missions",
        json={"goal": "Verify live web dashboard state", "repo_ref": "HEAD", "risk": "LOW"},
    )
    assert r_create.status_code == 201
    mid = r_create.json()["mission_id"]

    r_list = c.get("/v1/missions")
    assert r_list.status_code == 200
    m_list = r_list.json().get("missions", [])
    assert any(m["mission_id"] == mid for m in m_list)

    r_dash = c.get("/v1/dashboard")
    assert r_dash.status_code == 200
    dash = r_dash.json()
    assert dash["active_missions"] >= 1
    assert "validated_improvements" in dash

    r_out = c.get("/v1/outcomes")
    assert r_out.status_code == 200
    assert isinstance(r_out.json().get("outcomes"), list)

    r_perf = c.get("/v1/performance")
    assert r_perf.status_code == 200
    perf = r_perf.json()
    assert perf["baseline"]["status"] == "not_measured"
    assert perf["pipeline"]["status"] == "not_measured"
