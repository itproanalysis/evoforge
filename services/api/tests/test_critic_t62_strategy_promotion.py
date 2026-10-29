"""Sealed (Critic) — T62 EvoCore strategy promotion (v3.8 §5 Route→Verify→Evolve→Promote; "AI that evolves how AI
builds"): every evolution run records the build strategy it used; strategies are compared on their EvoForge-side
verified rounds; a challenger becomes champion only when its Wilson 95% lower bound beats the champion's upper bound;
new runs default to the champion; every decision is stored."""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, evolution_rounds, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
ROOT = Path(__file__).resolve().parents[3]
APP = json.loads((ROOT / "evals" / "rounds_v1" / "mission_board.json").read_text(encoding="utf-8"))
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}
DEFAULT = {"max_attempts": 3, "accumulate_critic": True, "retire_stale": True}
LEAN = {"max_attempts": 1, "accumulate_critic": False, "retire_stale": False}


def _settle(limit=300):
    end = time.time() + limit
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    _settle()
    evolution_rounds.clear()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    yield
    _settle()
    evolution_rounds.clear()


def _stubs(monkeypatch):
    def builder(goal, sha, file_context=None, **k):
        n = int(re.search(r"Round (\d) ", goal).group(1))
        current = next(f["content"] for f in (file_context or []) if f["path"] == "board.py")
        d = "".join(difflib.unified_diff(current.splitlines(True), APP["rounds"][n - 1]["reference"].splitlines(True),
                                         "a/board.py", "b/board.py"))
        return {"diff": d, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        n = int(re.search(r"Round (\d) ", goal).group(1))
        return {"sealed_tests": [{"code": h["code"].replace("def test_", "def test_critic_")}
                                 for h in APP["rounds"][n - 1]["heldout"]], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)


def _run(body):
    r = c.post("/v1/evolution/runs", json=body)
    assert r.status_code == 202, r.text
    rid = r.json()["run_id"]
    end = time.time() + 900
    while time.time() < end:
        d = c.get(f"/v1/evolution/runs/{rid}").json()
        if d["status"] in ("succeeded", "failed"):
            return d
        time.sleep(0.5)
    pytest.fail("evolution run did not finish")


def _fake(rid, strategy, evo_states, t):
    rounds = [{"index": i + 1, "name": f"R{i + 1}",
               "sides": {"evoforge": {"status": s, "verified": s == "READY", "cost_cents": 10},
                         "single": {"status": "FAILED", "verified": False, "cost_cents": 5}}}
              for i, s in enumerate(evo_states)]
    doc = {"run_id": rid, "app_id": "mission_board", "status": "succeeded", "feedback": "critic",
           "created_at": t, "finished_at": t + 1, "manifest": {"rounds": len(evo_states)}, "rounds": rounds}
    if strategy is not None:
        doc["strategy"] = strategy
    evolution_rounds._save(doc)


def test_runs_record_their_strategy_and_respect_it(monkeypatch):
    _stubs(monkeypatch)
    d = _run({"app_id": "mission_board", "rounds": 2, "strategy": LEAN})
    assert d["strategy"] == LEAN and re.fullmatch(r"st_[0-9a-f]{10}", d["strategy_id"])
    assert d["manifest"]["strategy_id"] == d["strategy_id"]
    assert all(r["sides"]["evoforge"]["attempts"] <= 1 for r in d["rounds"])
    again = _run({"app_id": "mission_board", "rounds": 1, "strategy": dict(reversed(list(LEAN.items())))})
    assert again["strategy_id"] == d["strategy_id"]  # canonical: key order does not matter
    default = _run({"app_id": "mission_board", "rounds": 1})
    assert default["strategy"] == DEFAULT and default["strategy_id"] != d["strategy_id"]


def test_promotion_needs_non_overlapping_intervals(monkeypatch):
    _fake("r_champ", None, ["READY", "READY", "FAILED", "FAILED", "FAILED"] * 2, 1.0)  # default strategy, 4/10
    _fake("r_close", LEAN, ["READY", "READY", "READY", "FAILED", "READY"] * 2, 2.0)  # 8/10: overlaps 4/10
    s = c.get("/v1/evolution/strategies").json()
    champ = s["champion"]["strategy_id"]
    lean = next(x for x in s["candidates"] if x["strategy"] == LEAN)
    assert lean["evoforge"]["verified"] == 8 and lean["evoforge"]["rounds"] == 10
    r = c.post("/v1/evolution/strategies/promote", json={"strategy_id": lean["strategy_id"]})
    assert r.status_code == 409 and "overlap" in r.text.lower()
    assert c.get("/v1/evolution/strategies").json()["champion"]["strategy_id"] == champ
    assert c.post("/v1/evolution/strategies/promote", json={"strategy_id": "st_0000000000"}).status_code == 404


def test_clear_win_is_promoted_recorded_and_used_by_new_runs(monkeypatch):
    _fake("r_champ", None, ["READY", "FAILED", "FAILED", "FAILED", "FAILED"] * 2, 1.0)  # 2/10
    _fake("r_win", LEAN, ["READY"] * 10, 2.0)  # 10/10: lower bound 0.72 > 0.51 upper bound of 2/10
    lean_id = next(x["strategy_id"] for x in c.get("/v1/evolution/strategies").json()["candidates"]
                   if x["strategy"] == LEAN)
    r = c.post("/v1/evolution/strategies/promote", json={"strategy_id": lean_id})
    assert r.status_code == 200, r.text
    s = c.get("/v1/evolution/strategies").json()
    assert s["champion"]["strategy_id"] == lean_id
    assert s["decisions"][-1]["promoted"] == lean_id and s["decisions"][-1]["previous"] != lean_id
    _stubs(monkeypatch)
    d = _run({"app_id": "mission_board", "rounds": 1})
    assert d["strategy_id"] == lean_id and d["strategy"] == LEAN  # the champion is the new default


def test_invalid_strategy_rejected():
    for bad in ({"max_attempts": 0}, {"max_attempts": 4}, {"accumulate_critic": "yes"}, {"other": 1}):
        assert c.post("/v1/evolution/runs", json={"app_id": "mission_board", "strategy": bad}).status_code == 422
