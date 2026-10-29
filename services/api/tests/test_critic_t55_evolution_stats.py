"""Sealed (Critic) — T55 evolution statistics (v3.8 §9 KPI, "no 10x without evidence"): across finished evolution runs,
per side: verified rounds / rounds with a Wilson 95% interval, cost per verified round; a winner only when the
intervals do not overlap; unfinished runs and PENDING rounds never count."""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import evolution_rounds  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


def _wilson(k, n, z=1.96):
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, centre - half), min(1.0, centre + half)]


def _run(rid, status, evo, single, feedback="critic", evo_cost=10, single_cost=5, t=1.0):
    def side(states, cost):
        return [{"status": st, "verified": st == "READY", "cost_cents": cost} for st in states]
    e, s = side(evo, evo_cost), side(single, single_cost)
    return {"run_id": rid, "kind": "evolution_run", "app_id": "mission_board", "status": status, "feedback": feedback,
            "created_at": t, "finished_at": t + 1,
            "manifest": {"app_id": "mission_board", "rounds": len(evo)},
            "rounds": [{"index": i + 1, "name": f"R{i + 1}", "sides": {"evoforge": e[i], "single": s[i]}}
                       for i in range(len(evo))]}


@pytest.fixture(autouse=True)
def store():
    evolution_rounds.clear()
    yield
    evolution_rounds.clear()


def test_counts_only_finished_rounds_with_wilson_intervals():
    evolution_rounds._save(_run("evo_a", "succeeded", ["READY"] * 5, ["READY", "READY", "FAILED", "FAILED", "FAILED"]))
    evolution_rounds._save(_run("evo_b", "succeeded", ["READY", "READY", "READY", "UNVERIFIED", "READY"],
                                ["FAILED"] * 5, t=2.0))
    evolution_rounds._save(_run("evo_c", "running", ["READY", "PENDING", "PENDING", "PENDING", "PENDING"],
                                ["READY", "PENDING", "PENDING", "PENDING", "PENDING"], t=3.0))
    d = c.get("/v1/evolution/stats").json()
    assert d["runs"] == 2  # the running run is excluded entirely
    e, s = d["by_side"]["evoforge"], d["by_side"]["single"]
    assert (e["verified"], e["rounds"]) == (9, 10) and (s["verified"], s["rounds"]) == (2, 10)
    for got, (k, n) in ((e, (9, 10)), (s, (2, 10))):
        lo, hi = got["wilson95"]
        assert abs(lo - _wilson(k, n)[0]) < 1e-6 and abs(hi - _wilson(k, n)[1]) < 1e-6
    assert e["cost_cents"] == 100 and s["cost_cents"] == 50
    assert e["cost_per_verified_cents"] == round(100 / 9) and s["cost_per_verified_cents"] == 25
    assert d["comparison"] == "evoforge_better"  # 9/10 vs 2/10: intervals do not overlap


def test_overlapping_intervals_are_not_a_win():
    evolution_rounds._save(_run("evo_x", "succeeded", ["READY", "READY", "FAILED", "READY", "FAILED"],
                                ["READY", "FAILED", "READY", "FAILED", "FAILED"], single_cost=6))
    d = c.get("/v1/evolution/stats").json()
    assert d["comparison"] == "not_significant"
    assert d["by_side"]["single"]["cost_per_verified_cents"] == 15  # 30c / 2 verified


def test_empty_and_zero_verified():
    d = c.get("/v1/evolution/stats").json()
    assert d["runs"] == 0 and d["comparison"] == "not_significant"
    assert d["by_side"]["evoforge"]["rounds"] == 0 and d["by_side"]["evoforge"]["cost_per_verified_cents"] is None
    evolution_rounds._save(_run("evo_z", "succeeded", ["FAILED"] * 5, ["FAILED"] * 5))
    d = c.get("/v1/evolution/stats").json()
    assert d["by_side"]["single"]["verified"] == 0 and d["by_side"]["single"]["cost_per_verified_cents"] is None


def test_feedback_filter_and_proxy():
    evolution_rounds._save(_run("evo_h", "succeeded", ["READY"] * 5, ["FAILED"] * 5, feedback="heldout"))
    evolution_rounds._save(_run("evo_k", "succeeded", ["FAILED"] * 5, ["FAILED"] * 5, feedback="critic", t=2.0))
    assert c.get("/v1/evolution/stats", params={"feedback": "critic"}).json()["by_side"]["evoforge"]["verified"] == 0
    assert c.get("/v1/evolution/stats", params={"feedback": "heldout"}).json()["by_side"]["evoforge"]["verified"] == 5
    assert c.get("/v1/evolution/stats", params={"feedback": "oracle"}).status_code == 422
    web = Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "proxyPolicy.ts"
    assert "/v1/evolution/stats" in web.read_text(encoding="utf-8")
