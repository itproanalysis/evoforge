"""T55 evolution statistics across runs (read-only aggregates, no model calls)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta  # noqa: E402
from evoforge import evolution_rounds as ev  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


@pytest.fixture(autouse=True)
def fresh():
    ev.clear()
    yield
    ev.clear()


def _snap(status, cost):
    return {"status": status, "verified": status == "READY",
            "cost_cents": cost}


def _seed(run_id, status, feedback, rounds_sides, created_at=0.0):
    rounds = [{"index": i + 1, "name": f"R{i + 1}", "goal": "g",
               "sides": dict(sides)}
              for i, sides in enumerate(rounds_sides)]
    doc = {"run_id": run_id, "app_id": "mission_board", "title": "t",
           "status": status, "feedback": feedback, "created_at": created_at,
           "started_at": created_at, "finished_at": created_at,
           "manifest": None, "rounds": rounds, "totals": {}, "error": None}
    ev._save(doc)
    return doc


def test_stats_aggregates_filters_and_shapes():
    _seed("t55-a", "succeeded", "critic", [
        {"single": _snap("READY", 100), "evoforge": _snap("READY", 120)},
        {"single": _snap("UNVERIFIED", 50), "evoforge": _snap("READY", 60)},
    ], created_at=1.0)
    _seed("t55-b", "failed", "heldout", [
        {"single": _snap("FAILED", 10), "evoforge": "PENDING"},
    ], created_at=2.0)
    _seed("t55-run", "running", "critic", [
        {"single": _snap("READY", 999), "evoforge": _snap("READY", 999)},
    ], created_at=3.0)
    r = c.get("/v1/evolution/stats")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["runs"] == 2
    single, evo = d["by_side"]["single"], d["by_side"]["evoforge"]
    assert single["rounds"] == 3 and single["verified"] == 1
    assert single["cost_cents"] == 160
    assert single["cost_per_verified_cents"] == 160
    assert evo["rounds"] == 2 and evo["verified"] == 2
    assert evo["cost_cents"] == 180
    assert evo["cost_per_verified_cents"] == 90
    for side in (single, evo):
        lo, hi = side["wilson95"]
        assert 0.0 <= lo <= hi <= 1.0
    assert d["comparison"] in ("evoforge_better", "single_better", "not_significant")
    assert "independent" in d["method"] and "approximation" in d["method"]
    rc = c.get("/v1/evolution/stats", params={"feedback": "critic"}).json()
    assert rc["runs"] == 1
    assert rc["by_side"]["single"]["rounds"] == 2
    rh = c.get("/v1/evolution/stats", params={"feedback": "heldout"}).json()
    assert rh["runs"] == 1
    assert rh["by_side"]["evoforge"]["rounds"] == 0
    assert rh["by_side"]["evoforge"]["wilson95"] == [0, 0]
    assert rh["by_side"]["evoforge"]["cost_per_verified_cents"] is None
    assert c.get("/v1/evolution/stats", params={"feedback": "oracle"}).status_code == 422


def test_stats_covers_all_runs_not_just_newest():
    for i in range(25):
        _seed(f"t55-many-{i:02d}", "succeeded", "critic", [
            {"single": _snap("READY", 10), "evoforge": _snap("UNVERIFIED", 10)},
        ], created_at=float(i))
    d = c.get("/v1/evolution/stats").json()
    assert d["runs"] == 25
    assert d["by_side"]["single"]["rounds"] == 25
    assert d["by_side"]["single"]["verified"] == 25


def test_stats_never_calls_a_model(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("stats must not call a model")
    monkeypatch.setattr(broker_meta, "call_builder", _boom)
    monkeypatch.setattr(broker_meta, "call_critic", _boom)
    _seed("t55-c", "succeeded", "critic", [
        {"single": _snap("READY", 10), "evoforge": _snap("READY", 10)},
    ])
    r = c.get("/v1/evolution/stats")
    assert r.status_code == 200


def test_proxy_allows_stats():
    policy = (WEB / "lib" / "proxyPolicy.ts").read_text(encoding="utf-8")
    assert "/v1/evolution/stats" in policy
