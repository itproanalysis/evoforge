"""T74 arena scoreboard summary (API)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import arena as arena_mod  # noqa: E402
from evoforge import commands, eval_jobs, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


def _settle(limit=60):
    end = time.time() + limit
    while time.time() < end and any(
            j["status"] in ("queued", "running")
            for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.2)


def setup_function(_fn):
    _settle()
    ledger.reset()
    ledger.configure({"default": 500000})
    commands.reset()
    eval_jobs.clear()
    arena_mod.clear()


def teardown_function(_fn):
    _settle()
    eval_jobs.clear()
    arena_mod.clear()
    ledger.reset()
    ledger.configure({"default": 500000})


def _doc(aid, status, winner, sp=0, sn=0, ep=0, en=0,
         sc=0, ec=0, judge=0):
    return {"arena_id": aid, "status": status,
            "suite_version": "v2", "task_id": "T", "model": "muse-spark-1.3",
            "goal": "g", "feedback": "critic",
            "created_at": time.time(), "started_at": time.time(),
            "finished_at": time.time(),
            "judge_cost_cents": judge,
            "lanes": {"single": {"status": "succeeded", "attempts": 1,
                                 "heldout": {"passed": sp, "n": sn},
                                 "outcome": "passed", "cost_cents": sc,
                                 "elapsed_ms": 1, "diff": "", "events": []},
                      "evoforge": {"status": "succeeded", "attempts": 1,
                                   "heldout": {"passed": ep, "n": en},
                                   "outcome": "passed", "cost_cents": ec,
                                   "elapsed_ms": 1, "diff": "", "events": []}},
            "verdict": {"winner": winner, "reason": "t"}, "error": None}


def test_summary_empty_zeros():
    r = c.get("/v1/arena/summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["running"] == 0
    assert body["failed"] == 0
    assert body["scored"] == 0
    assert body["unscorable"] == 0
    assert body["inconclusive"] == 0
    assert body["wins"] == {"evoforge": 0, "single": 0, "tie": 0}
    assert body["heldout"] == {"single": {"passed": 0, "n": 0},
                               "evoforge": {"passed": 0, "n": 0}}
    assert body["cost_cents"] == {"single": 0, "evoforge": 0, "judge": 0}
    assert isinstance(body["basis"], str) and body["basis"].strip()


def test_summary_aggregates_scored_only():
    arena_mod._save(_doc("a1", "succeeded", "evoforge", 1, 2, 2, 2, 10, 20, 5))
    arena_mod._save(_doc("a2", "succeeded", "tie", 0, 1, 0, 1, 3, 4, 0))
    bad = _doc("a3", "succeeded", "unscorable", 9, 9, 9, 9, 99, 99, 7)
    arena_mod._save(bad)
    inc = _doc("a4", "failed", "inconclusive")
    inc["lanes"]["single"]["status"] = "failed"
    arena_mod._save(inc)
    run = _doc("a5", "running", "tie")
    arena_mod._save(run)
    r = c.get("/v1/arena/summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 5
    assert body["running"] == 1
    assert body["failed"] == 1
    assert body["scored"] == 2
    assert body["unscorable"] == 1
    assert body["inconclusive"] == 1
    assert body["wins"] == {"evoforge": 1, "single": 0, "tie": 1}
    assert body["heldout"]["single"] == {"passed": 1, "n": 3}
    assert body["heldout"]["evoforge"] == {"passed": 2, "n": 3}
    assert body["cost_cents"] == {"single": 13, "evoforge": 24, "judge": 5}


def test_summary_not_shadowed_by_id_route():
    r = c.get("/v1/arena/summary")
    assert r.status_code == 200, r.text
    assert "wins" in r.json()
    r2 = c.get("/v1/arena/does-not-exist")
    assert r2.status_code == 404
