"""Muse T24 async eval jobs: background sealed measurements."""
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
from evoforge import broker_meta, commands, eval_jobs, ledger, performance  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
FAM = "simple_sequential"


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
    yield
    eval_jobs.clear()
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


def test_bad_kind_is_422():
    r = c.post("/v1/eval/jobs", json={"kind": "NOPE"})
    assert r.status_code == 422, r.text


def test_budget_refusal_creates_no_job_and_no_provider_call(monkeypatch):
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "1")

    def boom(*a, **k):
        raise AssertionError("provider called despite cap")

    monkeypatch.setattr(broker_meta, "call_builder", boom)
    before = ledger.snapshot()
    r = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE", "family": FAM})
    assert r.status_code == 402, r.text
    assert c.get("/v1/eval/jobs").json()["jobs"] == []
    after = ledger.snapshot()
    assert after["spent_cents"] == before["spent_cents"]
    assert after["reserved_cents"] == before["reserved_cents"]


def test_only_one_active_job_and_post_returns_immediately(monkeypatch):
    import threading

    entered = threading.Event()
    release = threading.Event()

    def blocking(goal, sha, file_context=None, **k):
        entered.set()
        assert release.wait(timeout=120), "job thread was not released"
        return {"diff": "", "tests": [], "rationale": "x", "stub": False,
                "model": "m", "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", blocking)
    start = time.time()
    r1 = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE", "family": FAM})
    elapsed = time.time() - start
    assert r1.status_code == 202, r1.text
    body = r1.json()
    assert body["status"] in ("queued", "running")
    j1 = body["job_id"]
    assert entered.wait(timeout=120), "builder did not run in background"
    # Returned while the builder was still blocked inside the worker.
    assert elapsed < 30
    # While the first job runs, the builder is blocked; a second POST must 409 fast.
    r2 = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE", "family": FAM})
    assert r2.status_code == 409, r2.text
    assert j1 in r2.text
    release.set()
    done = _wait(j1, timeout=180)
    assert done["status"] == "succeeded"


def test_baseline_job_success_records_measurement(monkeypatch):
    _stub_ok(monkeypatch)
    before = len(performance.history())
    r = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE", "family": FAM})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    done = _wait(job_id)
    assert done["status"] == "succeeded"
    assert done["error"] is None
    assert isinstance(done["result"], dict)
    assert done["result"]["baseline_id"]
    assert done["result"]["X_SINGLE"]["n"] == 2
    assert len(performance.history()) == before + 1
    perf = c.get("/v1/performance").json()
    assert perf["baseline"]["status"] == "measured"


def test_pipeline_job_success(monkeypatch):
    _stub_ok(monkeypatch)
    r = c.post("/v1/eval/jobs", json={"kind": "PIPELINE", "family": FAM})
    assert r.status_code == 202, r.text
    done = _wait(r.json()["job_id"], timeout=300)
    assert done["status"] == "succeeded"
    assert done["result"]["pipeline_id"]
    assert done["result"]["PIPELINE"]["n"] == 2


def test_job_failure_short_error_no_measurement(monkeypatch):
    def boom(goal, sha, file_context=None, **k):
        raise RuntimeError("boom-t24-failure")

    monkeypatch.setattr(broker_meta, "call_builder", boom)
    before = len(performance.history())
    r = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE", "family": FAM})
    assert r.status_code == 202, r.text
    done = _wait(r.json()["job_id"])
    assert done["status"] == "failed"
    assert done["result"] is None
    assert isinstance(done["error"], str) and done["error"]
    assert len(done["error"]) <= 300
    assert "RuntimeError" in done["error"]
    assert "def test_" not in done["error"]
    assert len(performance.history()) == before


def test_unknown_job_404():
    assert c.get("/v1/eval/jobs/job_doesnotexist").status_code == 404


def test_list_newest_first_at_most_20():
    for i in range(25):
        j = eval_jobs.create_job(kind="X_SINGLE", runner=lambda: {"ok": True})
        # Wait for the instant job to finish so the next create is allowed.
        deadline = time.time() + 10
        while time.time() < deadline:
            cur = eval_jobs.get_job(j["job_id"])
            if cur and cur["status"] not in ("queued", "running"):
                break
            time.sleep(0.01)
        time.sleep(0.005)
    r = c.get("/v1/eval/jobs")
    assert r.status_code == 200
    jobs = r.json()["jobs"]
    assert len(jobs) == 20
    ats = [j["created_at"] for j in jobs]
    assert ats == sorted(ats, reverse=True)
    for j in jobs:
        assert set(j) >= {"job_id", "kind", "status", "created_at",
                          "started_at", "finished_at", "result", "error"}
