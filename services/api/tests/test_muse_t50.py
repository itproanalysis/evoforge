"""Muse T50: Arena EvoForge lane with Critic feedback (v3.6 section 2.2).

In critic mode the EvoForge lane retries using only the independent
Critic's own spec-first tests (T47 semantics): one Critic call before the
first attempt, retry goals from Critic failures only, and the sealed
held-out suite judging the first all-Critic-pass attempt (else the last).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import arena as arena_mod  # noqa: E402
from evoforge import broker_meta, commands, eval_jobs, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
TASK_ID = "SV2-SS-01"


def _task() -> dict:
    return arena_mod.find_task("v2", TASK_ID)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset()
    ledger.configure({"default": 500000})
    commands.reset()
    eval_jobs.clear()
    arena_mod.clear()
    yield
    _drain(timeout=300)
    eval_jobs.clear()
    arena_mod.clear()
    ledger.reset()
    ledger.configure({"default": 500000})


def _drain(timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        try:
            jobs = c.get("/v1/eval/jobs").json().get("jobs", [])
            arenas = c.get("/v1/arena").json().get("arenas", [])
        except Exception:
            return
        if (not any(j.get("status") in ("queued", "running") for j in jobs)
                and not any(a.get("status") == "running" for a in arenas)):
            return
        time.sleep(0.5)


def _wait(aid, timeout=300):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = c.get(f"/v1/arena/{aid}")
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in ("succeeded", "failed"):
            return last
        time.sleep(0.5)
    raise AssertionError(f"arena {aid} did not finish: {last}")


def _heldout_names(task):
    return set(sealed_eval._heldout_test_names(task["heldout"]))


def _critic_ok(monkeypatch, calls, task):
    mod = sorted(task["files"])[0][:-3]

    def fake(goal, diff="", ci="", **k):
        calls.append({"goal": goal, "diff": diff, "ci": ci})
        return {"sealed_tests": [
            {"code": f"import {mod}\n\ndef test_critic_spec_ok():\n    assert {mod} is not None\n"}],
            "review": {"result": "PASS"}, "stub": False, "model": "muse-spark-1.3",
            "provider_calls": [],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50}}

    monkeypatch.setattr(broker_meta, "call_critic", fake)


def _fix_builder(monkeypatch, calls, task, fail_first=0):
    seen = []

    def fake(goal, sha, file_context=None, **k):
        calls.append(goal)
        seen.append(goal)
        if len(seen) <= fail_first:
            return {"diff": "", "tests": [], "rationale": "x", "stub": False,
                    "model": "muse-spark-1.3", "provider_calls": [],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}
        return {"diff": task["reference_fix"], "tests": [], "rationale": "x",
                "stub": False, "model": "muse-spark-1.3", "provider_calls": [],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}

    monkeypatch.setattr(broker_meta, "call_builder", fake)


def test_bad_feedback_is_422():
    assert c.post("/v1/arena", json={
        "suite_version": "v2", "task_id": TASK_ID,
        "feedback": "oracle"}).status_code == 422
    assert c.post("/v1/arena", json={
        "suite_version": "v2", "task_id": TASK_ID,
        "feedback": ""}).status_code == 422


def test_budget_guard_counts_the_extra_critic_call(monkeypatch):
    assert arena_mod.budget_worst_cents("heldout") == (
        1 + sealed_eval.PIPELINE_MAX_ATTEMPTS) * sealed_eval.BASELINE_COST_CENTS
    assert arena_mod.budget_worst_cents("critic") == (
        2 + sealed_eval.PIPELINE_MAX_ATTEMPTS) * sealed_eval.BASELINE_COST_CENTS
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "500")
    monkeypatch.setattr(broker_meta, "call_builder",
                        lambda *a, **k: pytest.fail("provider called despite cap"))
    monkeypatch.setattr(broker_meta, "call_critic",
                        lambda *a, **k: pytest.fail("provider called despite cap"))
    # 600c worst case in critic mode exceeds the 500c cap: refused pre-call.
    assert c.post("/v1/arena", json={
        "suite_version": "v2", "task_id": TASK_ID,
        "feedback": "critic"}).status_code == 402


def test_manifest_and_document_record_feedback_mode():
    task = _task()
    for mode, lane_feedback in (("heldout", "heldout_failing_test_names"),
                                ("critic", "critic")):
        doc = arena_mod.seed_running(f"aid_t50_{mode}", "v2", TASK_ID,
                                     "muse-spark-1.3", task, feedback=mode)
        try:
            assert doc["feedback"] == mode
            m = doc["manifest"]
            assert m["lanes"]["evoforge"]["feedback"] == lane_feedback
            assert m["lanes"]["single"]["feedback"] == "none"
            blob = json.dumps(m)
            assert task["reference_fix"] not in blob
            assert all(h["code"] not in blob for h in task["heldout"])
        finally:
            arena_mod.clear()
    heldout = arena_mod.build_manifest("v2", TASK_ID, "muse-spark-1.3", task)
    critic = arena_mod.build_manifest("v2", TASK_ID, "muse-spark-1.3", task,
                                      feedback="critic")
    assert "oracle" in heldout["disclosure"].lower()
    lowered = critic["disclosure"].lower()
    assert "no held-out signal" in lowered
    assert "critic" in lowered and "runner" in lowered


def test_critic_lane_passes_without_heldout_signal(monkeypatch):
    task = _task()
    critic_calls, builder_goals = [], []
    _critic_ok(monkeypatch, critic_calls, task)
    _fix_builder(monkeypatch, builder_goals, task)
    lane = arena_mod._run_evoforge_lane(task, "muse-spark-1.3", 60,
                                        feedback="critic")
    assert lane["status"] == "succeeded", lane
    assert lane["outcome"] == "passed", lane
    assert lane["heldout"]["passed"] == lane["heldout"]["n"] == len(task["heldout"])
    assert lane["attempts"] == 1
    assert isinstance(lane["cost_cents"], int) and lane["cost_cents"] > 0
    roles = [e.get("role") for e in lane["events"]]
    assert "critic" in roles, roles
    crit_msgs = [e["message"] for e in lane["events"] if e.get("role") == "critic"]
    assert any("Critic wrote 1 tests" in m for m in crit_msgs), crit_msgs
    assert any("attempt 1" in m and "Critic 1/1 passed" in m
               for m in crit_msgs), crit_msgs
    # One spec-first Critic call, goal plus file contents only.
    assert len(critic_calls) == 1
    assert critic_calls[0]["diff"] == "" and critic_calls[0]["ci"] == ""
    # The held-out suite never enters Builder goals.
    blob = json.dumps(builder_goals) + json.dumps(critic_calls)
    assert task["reference_fix"] not in blob
    assert all(h["code"] not in blob for h in task["heldout"])
    for name in _heldout_names(task):
        assert name not in blob, name


def test_critic_retry_goal_comes_only_from_critic_failures(monkeypatch):
    task = _task()
    critic_calls, builder_goals = [], []
    _critic_ok(monkeypatch, critic_calls, task)
    _fix_builder(monkeypatch, builder_goals, task, fail_first=1)
    lane = arena_mod._run_evoforge_lane(task, "muse-spark-1.3", 60,
                                        feedback="critic")
    assert lane["status"] == "succeeded", lane
    assert lane["outcome"] == "passed", lane
    assert lane["attempts"] == 2, lane
    assert "empty diff" in builder_goals[1]
    blob = json.dumps(builder_goals[1:])
    for name in _heldout_names(task):
        assert name not in blob, name
    for h in task["heldout"]:
        assert h["code"] not in blob


def test_http_critic_arena_end_to_end(monkeypatch):
    task = _task()
    _critic_ok(monkeypatch, [], task)
    lock = threading.Lock()
    calls = []

    def builder(goal, sha, file_context=None, **k):
        with lock:
            calls.append(goal)
        return {"diff": task["reference_fix"], "tests": [], "rationale": "x",
                "stub": False, "model": "muse-spark-1.3", "provider_calls": [],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}

    monkeypatch.setattr(broker_meta, "call_builder", builder)
    r = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK_ID,
                                  "feedback": "critic"})
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    running = c.get(f"/v1/arena/{aid}").json()
    assert running["status"] == "running", running
    assert running["feedback"] == "critic"
    assert running["manifest"]["lanes"]["evoforge"]["feedback"] == "critic"
    done = _wait(aid)
    assert done["status"] == "succeeded", done
    assert done["feedback"] == "critic"
    assert done["manifest"] == running["manifest"]
    evo, single = done["lanes"]["evoforge"], done["lanes"]["single"]
    assert evo["heldout"]["passed"] == evo["heldout"]["n"] == len(task["heldout"])
    assert single["attempts"] == 1
    assert isinstance(evo["cost_cents"], int) and evo["cost_cents"] > 0
    crit_msgs = [e["message"] for e in evo["events"] if e.get("role") == "critic"]
    assert any("Critic wrote" in m for m in crit_msgs), crit_msgs
    assert any("passed" in m for m in crit_msgs), crit_msgs
    for lane in (single, evo):
        assert lane.get("preview_source") in ("base", "candidate", "none"), lane
    blob = json.dumps(done)
    assert task["reference_fix"] not in blob
    assert all(h["code"] not in blob for h in task["heldout"])
    with lock:
        goals = list(calls)
    for name in _heldout_names(task):
        assert name not in json.dumps(goals), name
