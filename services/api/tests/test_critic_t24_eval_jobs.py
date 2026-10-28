"""Critic acceptance (sealed during build, promoted after) — T24 async eval jobs: measurements run outside the HTTP request, honest status, no leaks."""
from __future__ import annotations

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
from evoforge import broker_meta, commands, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"
FAMILY = "simple_sequential"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset()
    ledger.configure({"default": 500000})
    commands.reset()
    from evoforge import performance
    performance.clear()
    if hasattr(sealed_eval, "reset_measurements"):
        sealed_eval.reset_measurements()
    yield
    _drain()


def _drain(timeout=60):
    """Wait until no job is queued/running so tests never overlap."""
    end = time.time() + timeout
    while time.time() < end:
        r = c.get("/v1/eval/jobs")
        if r.status_code != 200:
            return
        jobs = r.json().get("jobs", [])
        if not any(j.get("status") in ("queued", "running") for j in jobs):
            return
        time.sleep(0.2)


def _wait(job_id, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/v1/eval/jobs/{job_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.2)
    pytest.fail(f"job {job_id} did not finish")


def _empty_builder(goal, sha, file_context=None, **k):
    return {"diff": "", "tests": [], "rationale": "x", "stub": False, "model": "m", "provider_calls": []}


def _tasks():
    return [t for s in sealed_eval.load_suites() if s.get("family") == FAMILY for t in s["tasks"]]


def _ref_builder():
    tasks = _tasks()

    def builder(goal, sha, file_context=None, **k):
        for t in tasks:
            if t["goal"] in goal or goal in t["goal"]:
                return {"diff": t["reference_fix"], "tests": [], "rationale": "x", "stub": False, "model": "m",
                        "provider_calls": []}
        return _empty_builder(goal, sha)
    return builder


# ---- accepted fast, runs outside the request ----

def test_job_post_returns_202_before_the_builder_finishes(monkeypatch):
    gate = threading.Event()

    def slow(goal, sha, file_context=None, **k):
        gate.wait(10)
        return _empty_builder(goal, sha)

    monkeypatch.setattr(broker_meta, "call_builder", slow)
    t0 = time.time()
    r = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE", "suite_version": "v0", "model": "muse-spark-1.3", "family": FAMILY})
    elapsed = time.time() - t0
    gate.set()
    assert r.status_code == 202, r.text
    body = r.json()
    assert re.fullmatch(r"[A-Za-z0-9_\-]{6,80}", body["job_id"]), body
    assert body["kind"] == "X_SINGLE" and body["status"] in ("queued", "running")
    assert elapsed < 5, f"POST blocked for {elapsed:.1f}s; the eval must run outside the request"
    done = _wait(body["job_id"])
    assert done["status"] == "succeeded", done


def test_succeeded_baseline_job_records_a_measurement(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _ref_builder())
    r = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE", "family": FAMILY})
    assert r.status_code == 202, r.text
    done = _wait(r.json()["job_id"])
    assert done["status"] == "succeeded", done
    assert done["finished_at"] >= done["started_at"] > 0
    res = done["result"]["measurement"]  # result is the sync endpoint body; counts live in its measurement
    assert res["n"] == len(_tasks()) and res["passed"] == len(_tasks()), res
    perf = c.get("/v1/performance").json()
    assert perf["baseline"]["status"] == "measured" and perf["baseline"]["passed"] == len(_tasks())


def test_pipeline_job_records_attempts(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _ref_builder())
    r = c.post("/v1/eval/jobs", json={"kind": "PIPELINE", "family": FAMILY})
    assert r.status_code == 202, r.text
    done = _wait(r.json()["job_id"])
    assert done["status"] == "succeeded", done
    perf = c.get("/v1/performance").json()["pipeline"]
    assert perf["status"] == "measured" and perf["passed"] == perf["n"] == len(_tasks())
    assert perf["attempts_total"] >= perf["n"]


# ---- guards ----

def test_budget_refusal_is_synchronous_402_and_creates_no_job(monkeypatch):
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "1")
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: pytest.fail("provider called despite cap"))
    before = c.get("/v1/eval/jobs").json()["jobs"]
    r = c.post("/v1/eval/jobs", json={"kind": "PIPELINE"})
    assert r.status_code == 402, r.text
    assert c.get("/v1/eval/jobs").json()["jobs"] == before
    assert ledger.snapshot()["spent_cents"] == 0 and ledger.snapshot()["reserved_cents"] == 0


def test_only_one_eval_job_runs_at_a_time(monkeypatch):
    gate = threading.Event()

    def slow(goal, sha, file_context=None, **k):
        gate.wait(10)
        return _empty_builder(goal, sha)

    monkeypatch.setattr(broker_meta, "call_builder", slow)
    first = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE", "family": FAMILY})
    assert first.status_code == 202, first.text
    second = c.post("/v1/eval/jobs", json={"kind": "PIPELINE", "family": FAMILY})
    gate.set()
    assert second.status_code == 409, second.text
    assert first.json()["job_id"] in second.text
    _wait(first.json()["job_id"])


def test_unknown_job_is_404_and_bad_kind_is_422():
    assert c.get("/v1/eval/jobs/job_does_not_exist").status_code == 404
    assert c.post("/v1/eval/jobs", json={"kind": "ANYTHING"}).status_code == 422


def test_failed_job_reports_error_and_records_nothing(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(broker_meta, "call_builder", boom)
    monkeypatch.setattr(sealed_eval, "run_baseline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("eval crashed")))
    r = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE", "family": FAMILY})
    assert r.status_code == 202, r.text
    done = _wait(r.json()["job_id"])
    assert done["status"] == "failed" and isinstance(done["error"], str) and done["error"]
    assert done.get("result") is None
    assert c.get("/v1/performance").json()["baseline"]["status"] == "not_measured"


def test_job_responses_never_leak_heldout_or_reference_fix(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _ref_builder())
    r = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE", "family": FAMILY})
    jid = r.json()["job_id"]
    done = _wait(jid)
    blob = r.text + json.dumps(done) + c.get("/v1/eval/jobs").text
    for t in _tasks():
        assert t["reference_fix"] not in blob
        for h in t["heldout"]:
            assert h["code"] not in blob
    assert "+++ " not in blob


def test_job_list_is_newest_first_with_status(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _empty_builder)
    ids = []
    for _ in range(2):
        r = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE", "family": FAMILY})
        assert r.status_code == 202, r.text
        ids.append(r.json()["job_id"])
        _wait(ids[-1])
    jobs = c.get("/v1/eval/jobs").json()["jobs"]
    listed = [j["job_id"] for j in jobs]
    assert listed.index(ids[1]) < listed.index(ids[0])
    assert all(j["status"] in ("queued", "running", "succeeded", "failed") for j in jobs)


# ---- web + proxy ----

def _read(rel):
    return (WEB / rel).read_text(encoding="utf-8")


def test_proxy_allows_eval_jobs_routes():
    src = _read("lib/proxyPolicy.ts")
    assert "/v1/eval/jobs" in src
    cases = json.loads(_read("lib/proxyPolicy.cases.json"))
    blob = json.dumps(cases)
    assert "/v1/eval/jobs" in blob


def test_api_client_and_page_use_jobs_and_poll():
    api = _read("lib/api.ts")
    assert "/v1/eval/jobs" in api
    page = _read("app/[locale]/performance/page.tsx")
    assert re.search(r"startEvalJob|createEvalJob|postEvalJob", api + page), "page must start eval via the jobs API"
    assert re.search(r"getEvalJob\b", api + page), "page must poll job status"
    assert re.search(r"setInterval|setTimeout", page), "page must poll until the job finishes"


def test_messages_have_job_status_keys_in_both_locales():
    ko = json.loads(_read("messages/ko.json"))
    en = json.loads(_read("messages/en.json"))

    def keys(d, p=""):
        out = set()
        for k, v in d.items():
            out |= keys(v, p + k + ".") if isinstance(v, dict) else {p + k}
        return out
    assert keys(ko) == keys(en)
    flat = " ".join(sorted(keys(ko))).lower()
    assert "job" in flat or "running" in flat, "job status strings must be localized"
