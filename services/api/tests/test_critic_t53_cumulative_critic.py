"""Sealed (Critic) — T53 cumulative Critic suite in evolution runs (v3.8 §3.2 regressions): in critic mode the EvoForge
lane keeps the Critic tests it got in earlier rounds and re-runs them every round, so a candidate that adds the new
feature but breaks an old one is retried before the held-out suite judges it — still with no held-out signal."""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
ROOT = Path(__file__).resolve().parents[3]
APP = json.loads((ROOT / "evals" / "rounds_v1" / "mission_board.json").read_text(encoding="utf-8"))
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}
GOOD_SUMMARY = "<p class=\"summary\">{done} of {len(tasks)} done</p>"
BAD_SUMMARY = "<p class=\"summary\">{done} of {len(tasks)} complete</p>"


def _settle(limit=300):
    end = time.time() + limit
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    _settle()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    yield
    _settle()


def _round_of(goal):
    m = re.search(r"Round (\d) ", goal or "")
    return int(m.group(1)) if m else 1


def _diff(old, new):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/board.py", "b/board.py"))


def _stubs(monkeypatch, goals):
    lock = threading.Lock()
    r3 = APP["rounds"][2]["reference"]
    assert GOOD_SUMMARY in r3
    broken_r3 = r3.replace(GOOD_SUMMARY, BAD_SUMMARY)  # adds the R3 feature, breaks R2's summary

    def builder(goal, sha, file_context=None, **k):
        n = _round_of(goal)
        current = next(f["content"] for f in (file_context or []) if f["path"] == "board.py")
        target = APP["rounds"][n - 1]["reference"]
        if n == 3 and "Previous attempt" not in goal:
            target = broken_r3
        with lock:
            goals.append((n, goal))
        return {"diff": _diff(current, target), "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        n = _round_of(goal)  # the Critic writes tests for the round it is asked about only
        return {"sealed_tests": [{"code": h["code"].replace("def test_", "def test_critic_")}
                                 for h in APP["rounds"][n - 1]["heldout"]], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)


def _run(rounds=3):
    r = c.post("/v1/evolution/runs", json={"app_id": "mission_board", "feedback": "critic", "rounds": rounds})
    assert r.status_code == 202, r.text
    rid = r.json()["run_id"]
    end = time.time() + 900
    while time.time() < end:
        d = c.get(f"/v1/evolution/runs/{rid}").json()
        if d["status"] in ("succeeded", "failed"):
            return d
        time.sleep(0.5)
    pytest.fail("evolution run did not finish")


def test_old_critic_tests_catch_a_regression_before_judging(monkeypatch):
    goals = []
    _stubs(monkeypatch, goals)
    d = _run()
    evo3 = d["rounds"][2]["sides"]["evoforge"]
    single3 = d["rounds"][2]["sides"]["single"]
    assert single3["status"] == "UNVERIFIED"  # one shot: the regression ships
    assert evo3["status"] == "READY" and evo3["attempts"] >= 2, evo3.get("status")
    retries = [g for n, g in goals if n == 3 and "Previous attempt" in g]
    assert retries and any("test_critic_r2_" in g for g in retries)  # R2's Critic test named the regression
    for _n, g in goals:
        for r in APP["rounds"]:
            for h in r["heldout"]:
                for name in re.findall(r"def (test_[A-Za-z0-9_]+)", h["code"]):
                    assert name not in g  # still no held-out signal


def test_snapshot_reports_the_critic_suite_size(monkeypatch):
    _stubs(monkeypatch, [])
    d = _run()
    sizes = [d["rounds"][i]["sides"]["evoforge"]["critic_tests"] for i in range(3)]
    assert sizes == [3, 6, 9]  # Critic tests accumulate round by round
    assert "critic_tests" not in d["rounds"][0]["sides"]["single"] or d["rounds"][0]["sides"]["single"]["critic_tests"] == 0
