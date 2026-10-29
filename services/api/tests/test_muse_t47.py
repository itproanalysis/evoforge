"""Muse T47: critic-feedback pipeline — retry signal from the Critic's own tests."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, ledger, performance, sealed_eval  # noqa: E402
from evoforge import eval_jobs as eval_jobs_mod  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
FAM = "simple_sequential"

CRITIC_FAIL = "def test_critic_gate_signal():\n    assert False, 'critic gate'\n"
CRITIC_PASS = "def test_critic_gate_ok():\n    assert True\n"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset()
    ledger.configure({"default": 500000})
    try:
        performance.clear()
    except Exception:
        pass
    main._evidence.clear()
    eval_jobs_mod.clear()
    yield
    ledger.reset()
    ledger.configure({"default": 500000})


def _tasks(family=FAM):
    return [t for s in sealed_eval.load_suites() for t in s["tasks"]
            if s["family"] == family]


def _known_names():
    return {m for t in _tasks() for m in sealed_eval._heldout_test_names(t["heldout"])}


def _critic_with(code, calls, usage=None):
    def fake(goal, diff="", ci="", **k):
        calls.append({"goal": goal, "diff": diff, "ci": ci})
        out = {"sealed_tests": [{"code": code, "kind": "compositional"}],
               "review": {"result": "INCONCLUSIVE", "findings": []},
               "stub": False, "model": "m", "provider_calls": []}
        if usage is not None:
            out["usage"] = dict(usage)
        return out

    return fake


def _fix_builder(goals, usage=None):
    by_goal = {t["goal"]: t for t in _tasks()}

    def builder(goal, sha, file_context=None, **k):
        goals.append(goal)
        t = next(v for g, v in by_goal.items() if g in goal or goal in g)
        out = {"diff": t["reference_fix"], "tests": [], "rationale": "t47",
               "stub": False, "model": "m", "provider_calls": []}
        if usage is not None:
            out["usage"] = dict(usage)
        return out

    return builder


def test_default_feedback_source_is_heldout(monkeypatch):
    goals = []
    monkeypatch.setattr(broker_meta, "call_builder",
                        _fix_builder(goals))
    result = sealed_eval.run_pipeline("v0", "muse-spark-1.3", family=FAM)
    assert result["feedback_source"] == "heldout"
    rec = performance.make_record(kind="PIPELINE", n=1, passed=1,
                                  cost_cents=1, evidence_id="ev_t47")
    assert rec["feedback_source"] == "heldout"


def test_invalid_feedback_rejected(monkeypatch):
    with pytest.raises(ValueError):
        sealed_eval.run_pipeline("v0", "muse-spark-1.3", family=FAM,
                                 feedback="bogus")
    with pytest.raises(ValueError):
        performance.make_record(kind="PIPELINE", n=1, passed=0,
                                cost_cents=0, evidence_id="e",
                                feedback_source="bogus")
    r = c.post("/v1/eval/pipeline",
               json={"suite_version": "v0", "model": "muse-spark-1.3",
                     "family": FAM, "feedback": "bogus"})
    assert r.status_code == 422, r.text
    r = c.post("/v1/eval/jobs",
               json={"kind": "PIPELINE", "suite_version": "v0",
                     "model": "muse-spark-1.3", "family": FAM,
                     "feedback": "bogus"})
    assert r.status_code == 422, r.text


def test_critic_feedback_never_sees_heldout(monkeypatch):
    goals, critic_calls = [], []
    monkeypatch.setattr(broker_meta, "call_builder", _fix_builder(goals))
    monkeypatch.setattr(broker_meta, "call_critic",
                        _critic_with(CRITIC_FAIL, critic_calls))
    result = sealed_eval.run_pipeline("v0", "muse-spark-1.3", family=FAM,
                                      feedback="critic")
    n = len(_tasks())
    assert result["feedback_source"] == "critic"
    assert result["PIPELINE"]["n"] == n
    # Critic never passes: every task exhausts all attempts, then the
    # held-out suite judges the last attempt (the reference fix passes).
    assert result["attempts_total"] == n * sealed_eval.PIPELINE_MAX_ATTEMPTS
    for s in result["scores"]:
        assert s["outcome"] == "passed" and s["score"] >= 1.0
    # One Critic call per task, before the first attempt, with goal and
    # file contents only (diff/ci empty).
    assert len(critic_calls) == n
    held_codes = [h["code"] for t in _tasks() for h in t["heldout"]]
    known = _known_names()
    for call in critic_calls:
        assert call["diff"] == "" and call["ci"] == ""
        assert "def test_" in call["goal"] or "path:" in call["goal"]
        for code in held_codes:
            assert code not in call["goal"]
        for name in known:
            assert name not in call["goal"]
    # Retry feedback carries only Critic failures, never held-out content.
    assert len(goals) == n * sealed_eval.PIPELINE_MAX_ATTEMPTS
    for i in range(0, len(goals), sealed_eval.PIPELINE_MAX_ATTEMPTS):
        assert _tasks()[i // sealed_eval.PIPELINE_MAX_ATTEMPTS]["goal"] in goals[i]
        for retry in goals[i + 1:i + sealed_eval.PIPELINE_MAX_ATTEMPTS]:
            assert "test_critic_gate_signal" in retry
            assert "critic gate" in retry
            for code in held_codes:
                assert code not in retry
            for name in known:
                assert name not in retry
    blob = json.dumps(result["scores"]) + json.dumps(result["tasks"])
    assert "def test_" not in blob and "test_critic_gate_signal" not in blob


def test_critic_pass_short_circuits_to_heldout_judgement(monkeypatch):
    goals, critic_calls = [], []
    monkeypatch.setattr(broker_meta, "call_builder", _fix_builder(goals))
    monkeypatch.setattr(broker_meta, "call_critic",
                        _critic_with(CRITIC_PASS, critic_calls))
    result = sealed_eval.run_pipeline("v0", "muse-spark-1.3", family=FAM,
                                      feedback="critic")
    n = len(_tasks())
    assert result["attempts_total"] == n  # first attempt passes Critic
    for s in result["scores"]:
        assert s["outcome"] == "passed" and s["score"] >= 1.0
    assert all(t["goal"] == g for t, g in zip(_tasks(), goals))


def test_critic_empty_and_apply_feedback_says_so(monkeypatch):
    critic_calls = []
    monkeypatch.setattr(broker_meta, "call_critic",
                        _critic_with(CRITIC_FAIL, critic_calls))

    goals = []
    monkeypatch.setattr(broker_meta, "call_builder",
                        lambda goal, sha, file_context=None, **k: (
                            goals.append(goal),
                            {"diff": "", "tests": [], "rationale": "x",
                             "stub": False, "model": "m",
                             "provider_calls": []})[1])
    result = sealed_eval.run_pipeline("v0", "muse-spark-1.3", family=FAM,
                                      feedback="critic")
    for s in result["scores"]:
        assert s["outcome"] == "empty_diff" and s["score"] < 1.0
    n = len(_tasks())
    assert len(goals) == n * sealed_eval.PIPELINE_MAX_ATTEMPTS
    for i in range(0, len(goals), sealed_eval.PIPELINE_MAX_ATTEMPTS):
        for retry in goals[i + 1:i + sealed_eval.PIPELINE_MAX_ATTEMPTS]:
            assert "empty diff" in retry

    def broken_builder(goal, sha, file_context=None, **k):
        goals.append(goal)
        return {"diff": "this is not a unified diff", "tests": [],
                "rationale": "x", "stub": False, "model": "m",
                "provider_calls": []}

    del goals[:]
    monkeypatch.setattr(broker_meta, "call_builder", broken_builder)
    result = sealed_eval.run_pipeline("v0", "muse-spark-1.3", family=FAM,
                                      feedback="critic")
    for s in result["scores"]:
        assert s["outcome"] == "apply_failed" and s["score"] < 1.0
    assert len(goals) == n * sealed_eval.PIPELINE_MAX_ATTEMPTS
    for i in range(0, len(goals), sealed_eval.PIPELINE_MAX_ATTEMPTS):
        for retry in goals[i + 1:i + sealed_eval.PIPELINE_MAX_ATTEMPTS]:
            assert "did not apply" in retry


def test_critic_usage_settles_like_builder(monkeypatch):
    b_usage = {"prompt_tokens": 20000, "completion_tokens": 10000}
    c_usage = {"prompt_tokens": 5000, "completion_tokens": 2500}
    want_b = performance.usage_cost_cents(b_usage)
    want_c = performance.usage_cost_cents(c_usage)
    assert want_b and want_c
    goals, critic_calls = [], []
    monkeypatch.setattr(broker_meta, "call_builder",
                        _fix_builder(goals, usage=b_usage))
    monkeypatch.setattr(broker_meta, "call_critic",
                        _critic_with(CRITIC_FAIL, critic_calls,
                                     usage=c_usage))
    before = ledger.snapshot()["spent_cents"]
    result = sealed_eval.run_pipeline("v0", "muse-spark-1.3", family=FAM,
                                      feedback="critic")
    n = len(_tasks())
    assert result["usage_missing"] is False
    assert result["PIPELINE"]["cost_cents"] == (
        n * sealed_eval.PIPELINE_MAX_ATTEMPTS * want_b + n * want_c)
    assert ledger.snapshot()["spent_cents"] - before == (
        result["PIPELINE"]["cost_cents"])


def test_pipeline_http_carries_feedback_source(monkeypatch):
    goals, critic_calls = [], []
    monkeypatch.setattr(broker_meta, "call_builder", _fix_builder(goals))
    monkeypatch.setattr(broker_meta, "call_critic",
                        _critic_with(CRITIC_PASS, critic_calls))
    r = c.post("/v1/eval/pipeline",
               json={"suite_version": "v0", "model": "muse-spark-1.3",
                     "family": FAM, "feedback": "critic"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["feedback_source"] == "critic"
    assert body["measurement"]["feedback_source"] == "critic"
    perf = c.get("/v1/performance").json()
    assert perf["pipeline"]["feedback_source"] == "critic"
    assert perf["pipeline"]["record"]["feedback_source"] == "critic"
    assert any(m.get("feedback_source") == "critic"
               for m in perf["history"])
    blob = json.dumps(body["scores"]) + json.dumps(body["tasks"])
    assert "def test_" not in blob and "+++ " not in blob
    # Default stays heldout.
    r = c.post("/v1/eval/pipeline",
               json={"suite_version": "v0", "model": "muse-spark-1.3",
                     "family": FAM})
    assert r.status_code == 201, r.text
    assert r.json()["feedback_source"] == "heldout"


def test_jobs_pipeline_carries_feedback_source(monkeypatch):
    goals, critic_calls = [], []
    monkeypatch.setattr(broker_meta, "call_builder", _fix_builder(goals))
    monkeypatch.setattr(broker_meta, "call_critic",
                        _critic_with(CRITIC_PASS, critic_calls))
    r = c.post("/v1/eval/jobs",
               json={"kind": "PIPELINE", "suite_version": "v0",
                     "model": "muse-spark-1.3", "family": FAM,
                     "feedback": "critic"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    end = time.time() + 120
    job = None
    while time.time() < end:
        job = c.get(f"/v1/eval/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(0.2)
    assert job is not None and job["status"] == "succeeded", job
    assert job["result"]["feedback_source"] == "critic"
