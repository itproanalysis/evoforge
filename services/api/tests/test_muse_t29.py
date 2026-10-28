"""Muse T29: usage-derived X_SINGLE cost and per-task outcomes."""
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
from evoforge import broker_meta, ledger, performance, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
FAM = "simple_sequential"
NAME_RX = re.compile(r"^test_[A-Za-z0-9_]+$")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    ledger.reset()
    ledger.configure({"default": 500000})
    try:
        performance.clear()
    except Exception:
        pass
    main._evidence.clear()
    yield
    ledger.reset()
    ledger.configure({"default": 500000})


def _tasks(family=FAM):
    return [t for s in sealed_eval.load_suites() for t in s["tasks"]
            if s["family"] == family]


def _known_names():
    return {m for t in _tasks() for m in sealed_eval._heldout_test_names(t["heldout"])}


def _builder_with(diff_fn, usage=None):
    def builder(goal, sha, file_context=None, **k):
        out = {"diff": diff_fn(goal), "tests": [], "rationale": "t29",
               "stub": False, "model": "m", "provider_calls": []}
        if usage is not None:
            out["usage"] = dict(usage)
        return out

    return builder


def test_baseline_cost_comes_from_provider_usage(monkeypatch):
    usage = {"prompt_tokens": 20000, "completion_tokens": 10000}
    want_each = performance.usage_cost_cents(usage)
    assert want_each is not None and want_each != sealed_eval.BASELINE_COST_CENTS
    monkeypatch.setattr(broker_meta, "call_builder",
                        _builder_with(lambda goal: "", usage=usage))
    before = ledger.snapshot()["spent_cents"]
    result = sealed_eval.run_baseline("v0", "muse-spark-1.3", family=FAM)
    n = len(_tasks())
    assert result["X_SINGLE"]["n"] == n
    assert result["X_SINGLE"]["cost_cents"] == n * want_each
    assert result["usage_missing"] is False
    assert ledger.snapshot()["spent_cents"] - before == n * want_each
    for s in result["scores"]:
        assert s["outcome"] == "empty_diff" and s["failing_tests"] == []


def test_baseline_missing_usage_settles_cap_and_flags(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder",
                        _builder_with(lambda goal: ""))
    result = sealed_eval.run_baseline("v0", "muse-spark-1.3", family=FAM)
    n = len(_tasks())
    assert result["X_SINGLE"]["cost_cents"] == n * sealed_eval.BASELINE_COST_CENTS
    assert result["usage_missing"] is True


def test_baseline_overrun_settles_real_value(monkeypatch):
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0}
    want_each = performance.usage_cost_cents(usage)
    assert want_each is not None and want_each > sealed_eval.BASELINE_COST_CENTS
    # Tight budget: each 120c reservation still fits, but settling the real
    # per-task value pushes total spend past the budget.
    ledger.reset()
    ledger.configure({"default": 245})
    monkeypatch.setattr(broker_meta, "call_builder",
                        _builder_with(lambda goal: "", usage=usage))
    result = sealed_eval.run_baseline("v0", "muse-spark-1.3", family=FAM)
    n = len(_tasks())
    assert n == 2
    assert result["X_SINGLE"]["cost_cents"] == n * want_each
    assert result["usage_missing"] is False
    assert ledger.snapshot()["overruns"], "overrun above budget must be recorded"


def test_baseline_heldout_failed_names_only_names(monkeypatch):
    # Default stub diff applies (new file) but never fixes the defect.
    result = sealed_eval.run_baseline("v0", "muse-spark-1.3", family=FAM)
    assert result["usage_missing"] is True  # stub carries no usage
    known = _known_names()
    assert known
    for s in result["scores"]:
        assert s["outcome"] == "heldout_failed", s
        assert isinstance(s["failing_tests"], list) and s["failing_tests"]
        for name in s["failing_tests"]:
            assert NAME_RX.fullmatch(name), name
            assert name in known, name
    blob = json.dumps(result["scores"])
    assert "def test_" not in blob and "AssertionError" not in blob


def test_baseline_all_four_outcomes(monkeypatch):
    by_goal = {t["goal"]: t for t in _tasks()}
    mode = {"kind": "empty"}

    def builder(goal, sha, file_context=None, **k):
        kind = mode["kind"]
        if kind == "empty":
            return {"diff": "", "tests": [], "rationale": "x", "stub": False,
                    "model": "m", "provider_calls": []}
        if kind == "broken":
            return {"diff": "this is not a unified diff", "tests": [],
                    "rationale": "x", "stub": False, "model": "m",
                    "provider_calls": []}
        t = next(v for g, v in by_goal.items() if g in goal or goal in g)
        if kind == "fixed":
            return {"diff": t["reference_fix"], "tests": [], "rationale": "x",
                    "stub": False, "model": "m", "provider_calls": []}
        return {"diff": ("--- /dev/null\n+++ b/evoforge_goal.txt\n"
                         "@@ -0,0 +1 @@\n+no fix here\n"),
                "tests": [], "rationale": "x", "stub": False, "model": "m",
                "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", builder)
    expected = {"empty": "empty_diff", "broken": "apply_failed",
                "fixed": "passed", "unfixed": "heldout_failed"}
    for kind, outcome in expected.items():
        mode["kind"] = kind
        result = sealed_eval.run_baseline("v0", "muse-spark-1.3", family=FAM)
        assert len(result["scores"]) == len(_tasks())
        for s in result["scores"]:
            assert s["outcome"] == outcome, (kind, s)
            assert s["score"] >= 1.0 if outcome == "passed" else s["score"] < 1.0
            if outcome == "heldout_failed":
                assert s["failing_tests"], s
            else:
                assert s["failing_tests"] == [], s


def test_outcome_helpers_unit():
    assert sealed_eval._is_empty_diff(None)
    assert sealed_eval._is_empty_diff("")
    assert sealed_eval._is_empty_diff("   \n ")
    assert not sealed_eval._is_empty_diff("--- a/x\n+++ b/x\n")
    assert not sealed_eval._is_empty_diff({"diff": "x"})
    heldout = [{"code": "import mod\n\ndef test_alpha_one():\n    assert 1 == 1\n",
                "kind": "negative"}]
    assert sealed_eval._heldout_test_names(heldout) == ["test_alpha_one"]
    failures = [{"test": "test_heldout_1::test_alpha_one", "message": "E AssertionError: boom"},
                {"test": "held-out", "message": "assertion failed"}]
    assert sealed_eval._failing_test_names(failures, heldout) == ["test_alpha_one"]
    assert sealed_eval._failing_test_names([], heldout) == []


def test_pipeline_final_attempt_outcome_and_usage_cost(monkeypatch):
    usage = {"prompt_tokens": 20000, "completion_tokens": 10000}
    want_each = performance.usage_cost_cents(usage)
    monkeypatch.setattr(broker_meta, "call_builder",
                        _builder_with(lambda goal: "", usage=usage))
    result = sealed_eval.run_pipeline("v0", "muse-spark-1.3", family=FAM)
    n = len(_tasks())
    assert result["PIPELINE"]["n"] == n
    assert result["attempts_total"] == n * sealed_eval.PIPELINE_MAX_ATTEMPTS
    assert result["PIPELINE"]["cost_cents"] == (
        n * sealed_eval.PIPELINE_MAX_ATTEMPTS * want_each)
    assert result["usage_missing"] is False
    for s in result["scores"]:
        assert s["outcome"] == "empty_diff" and s["failing_tests"] == []


def test_pipeline_passed_and_heldout_failed_outcomes(monkeypatch):
    by_goal = {t["goal"]: t for t in _tasks()}

    def fixed_builder(goal, sha, file_context=None, **k):
        t = next(v for g, v in by_goal.items() if g in goal or goal in g)
        return {"diff": t["reference_fix"], "tests": [], "rationale": "x",
                "stub": False, "model": "m", "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", fixed_builder)
    result = sealed_eval.run_pipeline("v0", "muse-spark-1.3", family=FAM)
    for s in result["scores"]:
        assert s["outcome"] == "passed" and s["failing_tests"] == []
        assert s["score"] >= 1.0

    def miss_builder(goal, sha, file_context=None, **k):
        return {"diff": ("--- /dev/null\n+++ b/evoforge_goal.txt\n"
                         "@@ -0,0 +1 @@\n+no fix here\n"),
                "tests": [], "rationale": "x", "stub": False, "model": "m",
                "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", miss_builder)
    result = sealed_eval.run_pipeline("v0", "muse-spark-1.3", family=FAM)
    known = _known_names()
    for s in result["scores"]:
        assert s["outcome"] == "heldout_failed", s
        assert s["failing_tests"], s
        for name in s["failing_tests"]:
            assert NAME_RX.fullmatch(name) and name in known


def test_sync_response_and_stored_evidence_carry_outcomes(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder",
                        _builder_with(lambda goal: ""))
    r = c.post("/v1/eval/baseline",
               json={"suite_version": "v0", "model": "muse-spark-1.3",
                     "family": FAM})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["scores"]
    for s in body["scores"]:
        assert s["outcome"] == "empty_diff" and s["failing_tests"] == []
    ev = c.get(f"/v1/evidence/{body['evidence_id']}")
    assert ev.status_code == 200, ev.text
    for s in ev.json()["data"]["scores"]:
        assert s["outcome"] == "empty_diff" and s["failing_tests"] == []


def test_score_rows_still_equal_reference_hygiene_records(monkeypatch):
    import sys as _sys

    _ref = str(Path(__file__).resolve().parents[1].parents[1]
               / "docs" / "evoforge-v4.2" / "reference_impl")
    if _ref not in _sys.path:
        _sys.path.insert(0, _ref)
    import eval_hygiene

    monkeypatch.setattr(broker_meta, "call_builder",
                        _builder_with(lambda goal: ""))
    result = sealed_eval.run_baseline("v0", "muse-spark-1.3", family=FAM)
    assert set(result["X_SINGLE"]) == {"pass_rate", "n", "cost_cents",
                                       "usage_missing"}
    for s in result["scores"]:
        assert s["hygiene"] == "clean"
        assert set(s["scaffold"]) == {"name", "version", "turn_cap", "model",
                                      "harness_version"}
        assert eval_hygiene.score_record(s["task_id"], s["score"],
                                         s["scaffold"], []) == s
        assert s["outcome"] in sealed_eval.SCORE_OUTCOMES
        assert isinstance(s["failing_tests"], list)


def test_baseline_usage_missing_reaches_record_and_view(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder",
                        _builder_with(lambda goal: ""))
    result = sealed_eval.run_baseline("v0", "muse-spark-1.3", family=FAM)
    n = len(_tasks())
    assert result["X_SINGLE"]["cost_cents"] == n * sealed_eval.BASELINE_COST_CENTS
    assert result["usage_missing"] is True
    assert result["X_SINGLE"]["usage_missing"] is True
    r = c.post("/v1/eval/baseline",
               json={"suite_version": "v0", "model": "muse-spark-1.3",
                     "family": FAM})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["X_SINGLE"]["cost_cents"] == n * sealed_eval.BASELINE_COST_CENTS
    assert body["X_SINGLE"]["usage_missing"] is True


def test_baseline_with_usage_marks_nothing_missing(monkeypatch):
    usage = {"prompt_tokens": 20000, "completion_tokens": 10000}
    want_each = performance.usage_cost_cents(usage)
    monkeypatch.setattr(broker_meta, "call_builder",
                        _builder_with(lambda goal: "", usage=usage))
    result = sealed_eval.run_baseline("v0", "muse-spark-1.3", family=FAM)
    n = len(_tasks())
    assert result["X_SINGLE"]["cost_cents"] == n * want_each
    assert result["usage_missing"] is False
    assert result["X_SINGLE"]["usage_missing"] is False
    r = c.post("/v1/eval/baseline",
               json={"suite_version": "v0", "model": "muse-spark-1.3",
                     "family": FAM})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["X_SINGLE"]["cost_cents"] == n * want_each
    assert body["X_SINGLE"]["usage_missing"] is False
