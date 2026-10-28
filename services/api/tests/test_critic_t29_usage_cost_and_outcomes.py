"""Critic acceptance (sealed during build, promoted after) — T29: X_SINGLE cost comes from provider usage (like PIPELINE), and every task says why it
scored what it scored (no held-out code)."""
from __future__ import annotations

import difflib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
FAMILY = "simple_sequential"
OUTCOMES = {"passed", "empty_diff", "apply_failed", "heldout_failed"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.delenv("EVO_EVAL_MAX_CENTS", raising=False)
    ledger.reset()
    ledger.configure({"default": 500000})
    from evoforge import performance
    performance.clear()


def _tasks(version="v1"):
    return [t for s in sealed_eval.load_suites(version) if s["family"] == FAMILY for t in s["tasks"]]


def _out(diff, usage):
    o = {"diff": diff, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3", "provider_calls": []}
    if usage is not None:
        o["usage"] = usage
    return o


def _touch_diff(task):
    path, text = sorted(task["files"].items())[0]
    new = "# touched\n" + text
    return "".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))


def _baseline(builder, monkeypatch, version="v1"):
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    r = c.post("/v1/eval/baseline", json={"suite_version": version, "family": FAMILY})
    assert r.status_code == 201, r.text
    return r.json()


# ---- usage-derived X_SINGLE cost ----

def test_baseline_settles_each_call_from_provider_usage(monkeypatch):
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0}  # 125c at the default prices
    body = _baseline(lambda goal, sha, file_context=None, **k: _out("", usage), monkeypatch)
    n = len(_tasks())
    assert body["measurement"]["cost_cents"] == 125 * n, body["measurement"]
    assert ledger.snapshot()["spent_cents"] == 125 * n
    assert ledger.snapshot()["reserved_cents"] == 0
    assert body["measurement"].get("usage_missing") in (False, None)


def test_baseline_without_usage_settles_at_the_reservation_and_says_so(monkeypatch):
    body = _baseline(lambda goal, sha, file_context=None, **k: _out("", None), monkeypatch)
    n = len(_tasks())
    assert body["measurement"]["cost_cents"] == sealed_eval.BASELINE_COST_CENTS * n
    assert body["measurement"]["usage_missing"] is True
    perf = c.get("/v1/performance").json()["baseline"]
    assert perf["usage_missing"] is True


def test_usage_above_the_reservation_is_never_hidden(monkeypatch):
    usage = {"prompt_tokens": 0, "completion_tokens": 100_000_000}  # 42500c, far above the 120c reservation
    body = _baseline(lambda goal, sha, file_context=None, **k: _out("", usage), monkeypatch)
    n = len(_tasks())
    assert body["measurement"]["cost_cents"] == 42500 * n, "the real usage cost is recorded, not capped"
    snap = ledger.snapshot()
    assert snap["spent_cents"] == 42500 * n or snap.get("overruns"), "an overrun must show in the ledger"


# ---- per-task outcomes ----

def _scores(body):
    return {s["task_id"]: s for s in body["scores"]}


def test_outcome_empty_diff(monkeypatch):
    body = _baseline(lambda goal, sha, file_context=None, **k: _out("", {"prompt_tokens": 1}), monkeypatch)
    for tid, s in _scores(body).items():
        assert s["outcome"] == "empty_diff" and s["score"] == 0.0, s


def test_outcome_apply_failed(monkeypatch):
    bad = "--- a/nope.py\n+++ b/nope.py\n@@ -1 +1 @@\n-not in the file\n+x\n"
    body = _baseline(lambda goal, sha, file_context=None, **k: _out(bad, {"prompt_tokens": 1}), monkeypatch)
    assert {s["outcome"] for s in _scores(body).values()} == {"apply_failed"}


def test_outcome_heldout_failed_names_tests_without_code(monkeypatch):
    by_goal = {t["goal"]: t for t in _tasks()}
    body = _baseline(lambda goal, sha, file_context=None, **k: _out(_touch_diff(by_goal[goal]), {"prompt_tokens": 1}),
                     monkeypatch)
    blob = json.dumps(body)
    for t in _tasks():
        s = _scores(body)[t["id"]]
        assert s["outcome"] == "heldout_failed", s
        assert s["failing_tests"] and all(name.startswith("test_") for name in s["failing_tests"]), s
        for h in t["heldout"]:
            assert h["code"] not in blob


def test_outcome_passed(monkeypatch):
    by_goal = {t["goal"]: t for t in _tasks()}
    body = _baseline(lambda goal, sha, file_context=None, **k: _out(by_goal[goal]["reference_fix"], {"prompt_tokens": 1}),
                     monkeypatch)
    assert {s["outcome"] for s in _scores(body).values()} == {"passed"}
    assert all(s.get("failing_tests") in ([], None) for s in _scores(body).values())


def test_outcomes_are_in_the_stored_evidence_and_pipeline_too(monkeypatch):
    body = _baseline(lambda goal, sha, file_context=None, **k: _out("", {"prompt_tokens": 1}), monkeypatch)
    ev = c.get(f"/v1/evidence/{body['evidence_id']}").json()
    assert "empty_diff" in json.dumps(ev)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    r = c.post("/v1/eval/pipeline", json={"suite_version": "v1", "family": FAMILY})
    assert r.status_code == 201, r.text
    assert {s.get("outcome") for s in r.json()["scores"]} <= OUTCOMES
    assert all(s.get("outcome") in OUTCOMES for s in r.json()["scores"])
