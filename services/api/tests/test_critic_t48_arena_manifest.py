"""Sealed (Critic) — T48 Arena fairness manifest (v3.6 §2.2, §7.4, AT-17/AT-18): every arena states, before and after the
run, that both lanes got the same task spec, the same base tree and the same held-out tests, and what each lane was allowed
(harness, attempts, feedback source) and how cost was measured."""
from __future__ import annotations

import hashlib
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
from evoforge import broker_meta, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
TASK = "SV2-SS-01"
HEX64 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _task():
    return next(t for s in sealed_eval.load_suites("v2") for t in s["tasks"] if t["id"] == TASK)


def _spec_hash(t):
    blob = json.dumps({"goal": t["goal"], "files": t["files"]}, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _heldout_hash(t):
    blob = json.dumps([{"id": h["id"], "code": h["code"]} for h in t["heldout"]], sort_keys=True,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()



def _settle(limit=300):
    """Wait until no eval job (from this or an earlier test file) is active."""
    end = time.time() + limit
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)

@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    _settle()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    yield
    _settle()


def _builder(monkeypatch, calls):
    t = _task()
    lock = threading.Lock()

    def fake(goal, sha, file_context=None, **k):
        with lock:
            calls.append({"goal": goal, "files": json.dumps(file_context, sort_keys=True), "t": time.time()})
        return {"diff": t["reference_fix"], "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}
    monkeypatch.setattr(broker_meta, "call_builder", fake)


def _start():
    r = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK})
    assert r.status_code == 202, r.text
    return r.json()["arena_id"]


def _wait(aid):
    end = time.time() + 300
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("arena did not finish")


def test_manifest_is_present_while_running_and_matches_the_task(monkeypatch):
    calls = []
    _builder(monkeypatch, calls)
    aid = _start()
    running = c.get(f"/v1/arena/{aid}").json()
    m = running["manifest"]  # conditions are shown before any result exists
    t = _task()
    assert m["task_spec_hash"] == _spec_hash(t) and HEX64.match(m["task_spec_hash"])
    assert m["heldout_hash"] == _heldout_hash(t)
    assert m["heldout_count"] == len(t["heldout"])
    assert m["suite_version"] == "v2" and m["task_id"] == TASK
    done = _wait(aid)
    assert done["manifest"]["task_spec_hash"] == m["task_spec_hash"]
    assert done["manifest"]["heldout_hash"] == m["heldout_hash"]


def test_both_lanes_saw_the_same_spec_and_base_tree(monkeypatch):
    calls = []
    _builder(monkeypatch, calls)
    a = _wait(_start())
    m = a["manifest"]
    assert re.fullmatch(r"[0-9a-f]{40}", m["base_tree_sha"]), m
    for lane in ("single", "evoforge"):
        assert a["lanes"][lane]["base_tree_sha"] == m["base_tree_sha"], lane
    first_two = calls[:2]
    assert len(first_two) == 2
    assert first_two[0]["goal"] == first_two[1]["goal"] == _task()["goal"]
    assert first_two[0]["files"] == first_two[1]["files"]
    assert abs(first_two[0]["t"] - first_two[1]["t"]) < 10, "lanes must start together"


def test_lane_allowances_and_cost_basis_are_disclosed(monkeypatch):
    _builder(monkeypatch, [])
    m = _wait(_start())["manifest"]
    single, evo = m["lanes"]["single"], m["lanes"]["evoforge"]
    assert single == {**single, "harness": "api-sealed-eval/1", "max_attempts": 1, "feedback": "none"}
    assert evo["harness"] == "api-sealed-eval/2"
    assert evo["max_attempts"] == sealed_eval.PIPELINE_MAX_ATTEMPTS
    assert evo["feedback"] in ("heldout_failing_test_names", "critic")
    assert single["model"] == evo["model"] == "muse-spark-1.3"
    assert m["cost_basis"] == "model_api_usage" and m["runner_cost"] == "not_measured"
    assert m["comparison_mode"] == "same_task_same_tests_concurrent"
    assert isinstance(m["disclosure"], str) and len(m["disclosure"]) >= 40


def test_manifest_leaks_no_heldout_code_or_reference_fix(monkeypatch):
    _builder(monkeypatch, [])
    a = _wait(_start())
    blob = json.dumps(a["manifest"])
    t = _task()
    assert t["reference_fix"] not in blob and all(h["code"] not in blob for h in t["heldout"])


def test_listed_arenas_carry_the_spec_hash(monkeypatch):
    _builder(monkeypatch, [])
    a = _wait(_start())
    row = next(x for x in c.get("/v1/arena").json()["arenas"] if x["arena_id"] == a["arena_id"])
    assert row["manifest"]["task_spec_hash"] == a["manifest"]["task_spec_hash"]
