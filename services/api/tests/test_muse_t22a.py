"""Builder checks for T22a performance backend (measured-only)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import ledger, performance, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.delenv("EVO_EVAL_MAX_CENTS", raising=False)
    ledger.reset()
    ledger.configure({"default": 500000})
    performance.clear()


def test_performance_starts_not_measured():
    r = c.get("/v1/performance")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["baseline"]["status"] == "not_measured"
    assert body["pipeline"]["status"] == "not_measured"
    assert body["comparison"]["status"] == "not_measured"
    assert body["comparison"]["delta_pp"] is None
    assert body["comparison"]["verdict"] is None
    assert body["cost_per_solved_cents"] == {"baseline": None, "pipeline": None}
    assert body["history"] == []
    assert body["storage"] == "memory"
    text = json.dumps(body)
    assert "def test_" not in text and "reference_fix" not in text
    # no measured numbers leak as defaults
    assert "pass_rate" not in json.dumps(body["baseline"]) or \
        body["baseline"].get("pass_rate") is None


def test_usage_cost_is_derived_and_rounded_up(monkeypatch):
    monkeypatch.setenv("EVO_PRICE_INPUT_PER_MTOK", "1.25")
    monkeypatch.setenv("EVO_PRICE_OUTPUT_PER_MTOK", "4.25")
    monkeypatch.setenv("EVO_PRICE_CACHE_READ_PER_MTOK", "0.15")
    got = performance.usage_cost_cents({"prompt_tokens": 1000000,
                                        "completion_tokens": 0})
    assert got == 125  # 1.25 USD -> 125c
    assert performance.usage_cost_cents({}) is None
    assert performance.usage_cost_cents(None) is None


def test_budget_refuses_when_cap_too_small(monkeypatch):
    monkeypatch.setattr(sealed_eval, "count_tasks", lambda *a, **k: 12)  # (family, suite_version) since W13
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "1")
    r = c.post("/v1/eval/pipeline",
               json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code == 402, r.text


def test_pipeline_stores_measurement_without_code_leak(monkeypatch):
    monkeypatch.setattr(sealed_eval, "count_tasks", lambda *a, **k: 2)  # (family, suite_version) since W13
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")

    def fake_run(suite_version, model, family=None):
        return {"pipeline_id": "pl_test", "suite_version": "v0",
                "model": "muse-spark-1.3",
                "PIPELINE": {"pass_rate": 0.5, "n": 2, "cost_cents": 7,
                             "attempts_total": 4},
                "pass_rate_wilson_lo": 0.1, "pass_rate_wilson_hi": 0.9,
                "scaffold": {"name": "s", "version": "v0", "turn_cap": 3,
                             "model": model, "harness_version": "h"},
                "audit": {}, "scores": [{"task_id": "t", "score": 1.0},
                                   {"task_id": "t2", "score": 0.0}],
                "tasks": [{"id": "t", "family": "f",
                           "kind": "boundary", "code_sha256": "x",
                           "code_len": 3}],
                "by_family": {"f": {"n": 2, "passed": 1, "pass_rate": 0.5,
                                    "cost_cents": 7}},
                "reservation_id": "", "reservation_ids": [],
                "provider_stub": True, "attempts_total": 4,
                "usage_missing": False}

    monkeypatch.setattr(sealed_eval, "run_pipeline", fake_run)
    r = c.post("/v1/eval/pipeline",
               json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code == 201, r.text
    body = json.dumps(r.json())
    assert "def test_" not in body and "reference_fix" not in body
    perf = c.get("/v1/performance").json()
    assert perf["pipeline"]["status"] == "measured"
    assert perf["pipeline"]["n"] == 2
    assert perf["pipeline"]["attempts_total"] == 4
    assert perf["comparison"]["status"] == "not_measured"
    assert perf["cost_per_solved_cents"]["pipeline"] == 7


def test_comparison_verdict_uses_wilson():
    base = performance.make_record(
        kind="X_SINGLE", suite_version="v0", model="muse-spark-1.3",
        harness_version="h", n=12, passed=2, cost_cents=100,
        per_family={}, evidence_id="ev1")
    pipe = performance.make_record(
        kind="PIPELINE", suite_version="v0", model="muse-spark-1.3",
        harness_version="h", n=12, passed=11, cost_cents=200,
        per_family={}, evidence_id="ev2", attempts_total=20)
    # force non-overlapping intervals for a deterministic verdict
    base["wilson95"] = [0.0, 0.4]
    pipe["wilson95"] = [0.6, 1.0]
    out = performance.compare(base, pipe)
    assert out["status"] == "measured" and out["verdict"] == "improved"
    assert out["delta_pp"] == pytest.approx(100.0 * (11 / 12 - 2 / 12))
