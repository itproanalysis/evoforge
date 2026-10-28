"""Critic acceptance (sealed during build, promoted after) — T35: the service decides its own harness adoption (roadmap M2): champion vs challenger on one
suite, adopt only on non-overlapping Wilson intervals, decision stored with both measurements."""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
H1, H2 = "api-sealed-eval/1", "api-sealed-eval/2"


def _overcount(diff):
    return re.sub(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@",
                  lambda m: f"@@ -{m.group(1)},{int(m.group(2)) + 1} +{m.group(3)},{int(m.group(4)) + 1} @@",
                  diff, flags=re.M)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    from evoforge import performance
    performance.clear()
    yield
    end = time.time() + 120
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.2)


def _builder(monkeypatch, miscount):
    tasks = {t["goal"]: t for s in sealed_eval.load_suites("v2") for t in s["tasks"]}
    monkeypatch.setattr(broker_meta, "call_builder", lambda goal, sha, file_context=None, **k: {
        "diff": (_overcount if miscount else (lambda d: d))(tasks[goal]["reference_fix"]) if goal in tasks else "",
        "tests": [], "rationale": "x", "stub": False, "model": "m", "provider_calls": []})


def _decide(body):
    r = c.post("/v1/eval/abtest", json=body)
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    end = time.time() + 300
    while time.time() < end:
        j = c.get(f"/v1/eval/jobs/{jid}").json()
        if j["status"] in ("succeeded", "failed"):
            return j
        time.sleep(0.3)
    pytest.fail("abtest job did not finish")


BODY = {"suite_version": "v2", "kind": "X_SINGLE", "family": "simple_sequential", "champion": H1, "challenger": H2}


def test_clear_win_is_adopted_with_both_measurements(monkeypatch):
    _builder(monkeypatch, miscount=True)  # strict harness rejects every diff, recount applies all
    j = _decide(BODY)
    assert j["status"] == "succeeded", j
    d = j["result"]["decision"]
    assert d["decision"] == "adopt" and d["challenger"] == H2 and d["champion"] == H1
    assert d["champion_measurement"]["passed"] == 0 and d["challenger_measurement"]["passed"] == 6
    assert d["challenger_measurement"]["wilson95"][0] > d["champion_measurement"]["wilson95"][1]
    hist = c.get("/v1/performance").json()["history"]
    assert {h["harness_version"] for h in hist} >= {H1, H2}


def test_no_clear_difference_keeps_the_champion(monkeypatch):
    _builder(monkeypatch, miscount=False)  # both harnesses apply correct diffs: identical results
    d = _decide(BODY)["result"]["decision"]
    assert d["decision"] == "keep" and "no_clear_difference" in d["reason"]


def test_decisions_are_listed_newest_first(monkeypatch):
    _builder(monkeypatch, miscount=True)
    _decide(BODY)
    _builder(monkeypatch, miscount=False)
    _decide(BODY)
    ds = c.get("/v1/eval/decisions").json()["decisions"]
    assert [x["decision"] for x in ds[:2]] == ["keep", "adopt"]
    assert all(x["suite_version"] == "v2" and x["kind"] == "X_SINGLE" for x in ds[:2])


def test_invalid_requests_are_refused():
    assert c.post("/v1/eval/abtest", json={**BODY, "challenger": H1}).status_code in (400, 422)  # same harness
    assert c.post("/v1/eval/abtest", json={**BODY, "challenger": "api-sealed-eval/9"}).status_code == 422


def test_budget_guard_covers_both_runs(monkeypatch):
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "1")
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: pytest.fail("provider called despite cap"))
    assert c.post("/v1/eval/abtest", json=BODY).status_code == 402
