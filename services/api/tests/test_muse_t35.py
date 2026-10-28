"""Muse T35 champion/challenger harness adoption."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, commands, decisions, eval_jobs, ledger, performance  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
FAM = "simple_sequential"
CHAMP = "api-sealed-eval/1"
CHALL = "api-sealed-eval/2"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.delenv("EVO_EVAL_MAX_CENTS", raising=False)
    ledger.reset()
    ledger.configure({"default": 500000})
    commands.reset()
    try:
        performance.clear()
    except Exception:
        pass
    eval_jobs.clear()
    decisions.clear()
    yield
    eval_jobs.clear()
    decisions.clear()
    try:
        performance.clear()
    except Exception:
        pass
    ledger.reset()
    ledger.configure({"default": 500000})


def _stub_ok(monkeypatch):
    def builder(goal, sha, file_context=None, **k):
        return {"diff": "", "tests": [], "rationale": "x", "stub": False,
                "model": "m", "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", builder)


def _wait(job_id, timeout=300):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = c.get(f"/v1/eval/jobs/{job_id}")
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in ("succeeded", "failed"):
            return last
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} did not finish: {last}")


def test_same_harness_is_400():
    r = c.post("/v1/eval/abtest", json={
        "kind": "X_SINGLE", "family": FAM,
        "champion": CHAMP, "challenger": CHAMP})
    assert r.status_code == 400, r.text


def test_budget_guard_before_any_provider_call(monkeypatch):
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "1")

    def boom(*a, **k):
        raise AssertionError("provider called despite cap")

    monkeypatch.setattr(broker_meta, "call_builder", boom)
    before = len(performance.history())
    r = c.post("/v1/eval/abtest", json={
        "kind": "X_SINGLE", "family": FAM,
        "champion": CHAMP, "challenger": CHALL})
    assert r.status_code == 402, r.text
    assert c.get("/v1/eval/jobs").json()["jobs"] == []
    assert c.get("/v1/eval/decisions").json()["decisions"] == []
    assert len(performance.history()) == before


def test_abtest_success_records_two_measurements_and_decision(monkeypatch):
    _stub_ok(monkeypatch)
    before = len(performance.history())
    r = c.post("/v1/eval/abtest", json={
        "kind": "X_SINGLE", "family": FAM,
        "champion": CHAMP, "challenger": CHALL})
    assert r.status_code == 202, r.text
    done = _wait(r.json()["job_id"])
    assert done["status"] == "succeeded", done
    decision = done["result"]["decision"]
    assert decision["suite_version"] == "v2"
    assert decision["kind"] == "X_SINGLE"
    assert decision["model"] == "muse-spark-1.3"
    assert decision["family"] == FAM
    assert decision["champion"] == CHAMP
    assert decision["challenger"] == CHALL
    assert decision["decision_id"]
    assert decision["created_at"]
    assert decision["verdict"] in ("improved", "no_clear_difference", "worse")
    assert decision["decision"] == ("adopt" if decision["verdict"] == "improved" else "keep")
    assert decision["verdict"] in decision["reason"]
    assert decision["champion_measurement"]["harness_version"] == CHAMP
    assert decision["challenger_measurement"]["harness_version"] == CHALL
    assert len(performance.history()) == before + 2
    got = c.get("/v1/eval/decisions")
    assert got.status_code == 200
    stored = got.json()["decisions"]
    assert len(stored) == 1
    assert stored[0]["decision_id"] == decision["decision_id"]
