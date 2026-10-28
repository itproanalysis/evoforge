"""Critic acceptance (sealed during build, promoted after) — T22a backend: measured-only numbers, honest verdicts, leak-free feedback."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, commands, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"
MARK = "T22_HELDOUT_MARK_8080"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.delenv("EVO_EVAL_MAX_CENTS", raising=False)
    ledger.reset()
    ledger.configure({"default": 500000})
    commands.reset()
    if hasattr(sealed_eval, "reset_measurements"):
        sealed_eval.reset_measurements()
    from evoforge import performance as _perf
    _perf.clear()  # measurements are process-wide; each test starts with none


def _rec(kind, passed, n, cost, suite="v0", model="muse-spark-1.3"):
    from evoforge import performance
    return performance.make_record(kind=kind, suite_version=suite, model=model, harness_version="h-test", passed=passed, n=n,
                                   cost_cents=cost, per_family={}, evidence_id="ev_test")


# ---- measured-only ----

def test_no_measurements_means_not_measured_and_no_numbers():
    body = c.get("/v1/performance").json()
    assert body["baseline"]["status"] == "not_measured" and body["baseline"]["reason"]
    assert body["pipeline"]["status"] == "not_measured" and body["pipeline"]["reason"]
    assert body["comparison"]["status"] == "not_measured"
    assert body["comparison"]["delta_pp"] is None and body["comparison"]["verdict"] is None
    assert body["cost_per_solved_cents"] == {"baseline": None, "pipeline": None}
    assert body["history"] == []
    assert body["storage"] in ("memory", "postgres")  # honest about where numbers live


def test_comparison_verdict_uses_wilson_intervals():
    from evoforge import performance as P
    base = _rec("X_SINGLE", 3, 12, 40)
    better = _rec("PIPELINE", 11, 12, 300)  # Wilson lo 0.646 > base hi 0.532
    same = _rec("PIPELINE", 4, 12, 300)     # intervals overlap
    assert P.compare(base, better)["verdict"] == "improved"
    assert P.compare(base, same)["verdict"] == "no_clear_difference"
    # 'worse' needs a high baseline: base 10/12 has lo 0.552, pipeline 0/12 has hi 0.243
    high = _rec("X_SINGLE", 10, 12, 40)
    assert P.compare(high, _rec("PIPELINE", 0, 12, 300))["verdict"] == "worse"
    # the low-baseline case overlaps and must NOT be called worse (0/12 hi 0.243 > 3/12 lo 0.089)
    assert P.compare(base, _rec("PIPELINE", 0, 12, 300))["verdict"] == "no_clear_difference"
    cmp = P.compare(base, better)
    assert cmp["delta_pp"] == pytest.approx(100 * (11 / 12 - 3 / 12), abs=0.01)


def test_overlapping_intervals_never_claim_improvement():
    from evoforge import performance as P
    base = _rec("X_SINGLE", 5, 12, 40)
    pipe = _rec("PIPELINE", 7, 12, 300)  # small sample, intervals overlap
    assert P.compare(base, pipe)["verdict"] == "no_clear_difference"


def test_mismatched_suite_or_model_is_not_comparable():
    from evoforge import performance as P
    base = _rec("X_SINGLE", 3, 12, 40, suite="v0")
    pipe = _rec("PIPELINE", 11, 12, 300, suite="v1")
    cmp = P.compare(base, pipe)
    assert cmp["status"] == "not_measured" and cmp["delta_pp"] is None and cmp["verdict"] is None


def test_cost_per_solved_is_integer_and_null_when_no_solves():
    from evoforge import performance as P
    assert P.cost_per_solved(_rec("X_SINGLE", 0, 12, 40)) is None
    assert P.cost_per_solved(_rec("X_SINGLE", 4, 12, 40)) == 10
    # integer cents: 41 / 4 is not whole, so the value must be a rounded int, never a float
    val = P.cost_per_solved(_rec("X_SINGLE", 4, 12, 41))
    assert isinstance(val, int) and val == 10


def test_production_sample_counts_match_runs_evidence(monkeypatch):
    from evoforge import runner
    monkeypatch.setattr(runner, "run_candidate", lambda *a, **k: {
        "base": "b" * 40, "hygiene": [], "heldout_kinds": ["compositional", "negative", "boundary"],
        "visible": {"pass": 1, "n": 1, "timed_out": False, "exit_code": 0},
        "heldout": {"pass": 3, "n": 3, "timed_out": False, "exit_code": 0}})
    import evoforge.repo_source as rs
    tmp = Path(__file__).parent
    monkeypatch.setattr(rs, "resolve_repo_dir", lambda *a, **k: str(tmp))
    from critic_helpers import sealed_suite, server_review
    rid = server_review(c, monkeypatch, sealed_suite())
    for _ in range(2):
        r = c.post("/v1/runs", json={"source_repo": "", "base_sha": "b" * 40, "diff": "", "tests": [],
                                     "review_evidence_id": rid})
        assert r.status_code in (200, 409, 400), r.text
    prod = c.get("/v1/performance").json()["production"]
    runs = [v for v in main._evidence.values() if isinstance(v.get("run"), dict)]
    assert prod["runs"] == len(runs) >= 1
    assert prod["gate_pass"] + prod["gate_fail"] + prod["gate_inconclusive"] == prod["runs"]
    assert "n" in prod["sample_note"] or str(prod["runs"]) in prod["sample_note"]


# ---- pipeline semantics and guardrails ----

def test_pipeline_budget_guard_refuses_before_any_provider_call(monkeypatch):
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "1")
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: pytest.fail("provider called despite cap"))
    r = c.post("/v1/eval/pipeline", json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code == 402, r.text
    assert ledger.snapshot()["spent_cents"] == 0 and ledger.snapshot()["reserved_cents"] == 0


def test_pipeline_feedback_never_contains_heldout_code(monkeypatch):
    calls = []

    def builder(goal, sha, file_context=None, feedback=None, **k):
        calls.append({"goal": goal, "file_context": file_context, "feedback": feedback})
        return {"diff": "", "tests": [], "rationale": "x", "stub": False, "model": "m", "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", builder)
    r = c.post("/v1/eval/pipeline", json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code in (201, 402), r.text
    blob = json.dumps(calls, default=str)
    assert MARK not in blob
    for t in sealed_eval.load_suites()[0]["tasks"]:
        for h in t["heldout"]:
            assert h["code"] not in blob
    assert "+++ " not in blob  # reference fixes never reach the Builder
    # Feedback may name failing tests and their error lines only: it must not carry any held-out test source.
    held_lines = {ln.strip() for s in sealed_eval.load_suites() for t in s["tasks"] for h in t["heldout"]
                  for ln in h["code"].splitlines() if len(ln.strip()) > 15 and not ln.strip().startswith("def ")}
    for x in calls:
        if x["feedback"]:
            fb = json.dumps(x["feedback"], default=str)
            assert not any(line in fb for line in held_lines), "held-out source line leaked into feedback"


def test_pipeline_retries_and_costs_every_attempt(monkeypatch):
    attempts = []
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")

    def builder(goal, sha, file_context=None, feedback=None, **k):
        attempts.append(feedback is not None)
        return {"diff": "", "tests": [], "rationale": "x", "stub": False, "model": "m", "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", builder)
    before = ledger.snapshot()["spent_cents"]
    r = c.post("/v1/eval/pipeline", json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code == 201, r.text
    p = r.json()["PIPELINE"] if "PIPELINE" in r.json() else r.json()
    assert p["attempts_total"] == len(attempts) and 1 < len(attempts) <= 3 * p["n"]
    assert p["cost_cents"] == ledger.snapshot()["spent_cents"] - before and p["cost_cents"] > 0


def test_cost_is_derived_from_provider_usage_not_a_constant(monkeypatch):
    class _U:
        def __init__(self, p, c, r, cr):
            self.prompt_tokens, self.completion_tokens = p, c
            self.completion_tokens_details = type("D", (), {"reasoning_tokens": r})()
            self.prompt_tokens_details = type("P", (), {"cached_tokens": cr})()

    def builder(goal, sha, file_context=None, feedback=None, **k):
        # 1,000,000 prompt tokens at $1.25/M = 125 cents; 0 output; no cache
        return {"diff": "", "tests": [], "rationale": "x", "stub": False, "model": "m", "provider_calls": [],
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0, "reasoning_tokens": 0,
                          "cached_tokens": 0}}

    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000000")
    r = c.post("/v1/eval/pipeline", json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code == 201, r.text
    p = c.get("/v1/performance").json()["pipeline"]
    # every attempt costs its usage-derived 125 cents; total = attempts x 125 (not a fixed per-attempt constant)
    assert p["attempts_total"] >= p["n"] >= 1
    assert p["cost_cents"] == 125 * p["attempts_total"], (p["cost_cents"], p["attempts_total"])


def test_pipeline_task_passes_if_any_attempt_passes(monkeypatch):
    # Real scoring, no hooks: attempt 1 is empty (fails); attempt 2 is the task's reference fix (passes its
    # held-out suite). Every task must therefore pass on attempt 2, with feedback given before that attempt.
    tasks = [t for s in sealed_eval.load_suites() for t in s["tasks"]]
    seq, unmatched, calls = {}, [], []

    def fix_for(goal):
        # The pipeline may wrap the task goal; match by containment, and never swallow an unknown goal silently.
        for t in tasks:
            if t["goal"] in goal or goal in t["goal"]:
                return t["id"], t["reference_fix"]
        unmatched.append(goal)
        return None, ""

    def builder(goal, sha, file_context=None, **k):
        tid, ref = fix_for(goal)
        calls.append(tid)
        seq[tid] = seq.get(tid, 0) + 1
        diff = ref if seq.get(tid) == 2 else ""  # attempt 1 empty (fails); attempt 2 reference fix (passes)
        return {"diff": diff, "tests": [], "rationale": "x", "stub": False, "model": "m", "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    r = c.post("/v1/eval/pipeline", json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code == 201, r.text
    p = c.get("/v1/performance").json()["pipeline"]
    assert not unmatched, f"pipeline passed goals that match no sealed task: {unmatched[:2]}"
    assert p["passed"] == p["n"] == len(tasks), p
    assert p["attempts_total"] == 2 * p["n"]


# ---- leak-free HTTP ----

def test_performance_and_eval_responses_leak_nothing():
    for path in ("/v1/performance", "/v1/eval/suites"):
        r = c.get(path)
        assert r.status_code == 200
        assert MARK not in r.text and "def test_" not in r.text and "+++ " not in r.text


