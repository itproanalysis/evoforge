"""Sealed (Critic) — T50 Arena EvoForge lane with Critic feedback (v3.6 §2.2, §11): the EvoForge lane can retry using only
the independent Critic's own tests, so a win carries no held-out signal; the manifest and events say which mode ran."""
from __future__ import annotations

import difflib
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
from evoforge import broker_meta, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
TASK = "SV2-SS-01"


def _task():
    return next(t for s in sealed_eval.load_suites("v2") for t in s["tasks"] if t["id"] == TASK)


def _heldout_names(t):
    return sorted({m for h in t["heldout"] for m in re.findall(r"def (test_[A-Za-z0-9_]+)", h["code"])})


def _noop_diff(t):
    path = sorted(t["files"])[0]
    old = t["files"][path]
    return "".join(difflib.unified_diff(old.splitlines(True), (old + "\n# noop\n").splitlines(True),
                                        f"a/{path}", f"b/{path}"))



def _settle(limit=300):
    """Wait until no eval job (from this or an earlier test file) is active."""
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


def _stubs(monkeypatch, goals):
    t = _task()
    lock = threading.Lock()
    usage = {"prompt_tokens": 1000, "completion_tokens": 200}

    def builder(goal, sha, file_context=None, **k):
        with lock:
            goals.append(goal)
        diff = t["reference_fix"] if "Previous attempt" in goal else _noop_diff(t)
        return {"diff": diff, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": usage}

    # The Critic's own spec-first tests: same checks as the task needs, written under its own names.
    critic_code = [{"code": h["code"].replace("def test_", "def test_critic_")} for h in t["heldout"]]

    def critic(goal, diff, ci="", **k):
        return {"sealed_tests": critic_code, "stub": False, "usage": usage}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)


def _run(body):
    r = c.post("/v1/arena", json=body)
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    end = time.time() + 300
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("arena did not finish")


def test_critic_lane_wins_without_any_heldout_signal(monkeypatch):
    goals = []
    _stubs(monkeypatch, goals)
    a = _run({"suite_version": "v2", "task_id": TASK, "feedback": "critic"})
    evo, single = a["lanes"]["evoforge"], a["lanes"]["single"]
    assert single["heldout"]["passed"] < single["heldout"]["n"]
    assert evo["heldout"]["passed"] == evo["heldout"]["n"] and evo["attempts"] >= 2
    assert a["verdict"]["winner"] == "evoforge"
    retries = [g for g in goals if "Previous attempt" in g]
    assert retries, goals
    for g in goals:
        for name in _heldout_names(_task()):
            assert name not in g, (name, g[:300])
    assert any("test_critic_" in g for g in retries)


def test_manifest_and_events_name_the_mode_and_cost_includes_the_critic(monkeypatch):
    _stubs(monkeypatch, [])
    a = _run({"suite_version": "v2", "task_id": TASK, "feedback": "critic"})
    m = a["manifest"]
    assert m["lanes"]["evoforge"]["feedback"] == "critic" and m["lanes"]["single"]["feedback"] == "none"
    assert "held-out" not in m["disclosure"].lower() or "no held-out" in m["disclosure"].lower()
    roles = {e.get("role") for e in a["lanes"]["evoforge"]["events"]}
    assert "critic" in roles
    assert a["lanes"]["evoforge"]["cost_cents"] > a["lanes"]["single"]["cost_cents"]


def test_heldout_mode_stays_default_and_bad_mode_is_rejected(monkeypatch):
    _stubs(monkeypatch, [])
    a = _run({"suite_version": "v2", "task_id": TASK})
    assert a["manifest"]["lanes"]["evoforge"]["feedback"] == "heldout_failing_test_names"
    assert c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK, "feedback": "oracle"}).status_code == 422
