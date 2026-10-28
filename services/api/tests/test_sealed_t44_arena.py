"""Sealed (Critic) — T44 Arena engine (north star A1): one task, two lanes (EvoForge vs single AI), concurrent, both
scored by the same sealed held-out tests, usage cost per lane, honest verdict."""
from __future__ import annotations

import json
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
TASK = "SV2-SS-01"


def _task():
    return next(t for s in sealed_eval.load_suites("v2") for t in s["tasks"] if t["id"] == TASK)


def _overcount(diff):
    return re.sub(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@",
                  lambda m: f"@@ -{m.group(1)},{int(m.group(2)) + 1} +{m.group(3)},{int(m.group(4)) + 1} @@", diff, flags=re.M)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    yield
    end = time.time() + 120
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.2)


def _builder(monkeypatch, diff_fn):
    t = _task()
    usage = {"prompt_tokens": 1000, "completion_tokens": 200}
    monkeypatch.setattr(broker_meta, "call_builder", lambda goal, sha, file_context=None, **k: {
        "diff": diff_fn(t["reference_fix"]), "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
        "provider_calls": [], "usage": usage})


def _run(body=None):
    r = c.post("/v1/arena", json=body or {"suite_version": "v2", "task_id": TASK})
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    end = time.time() + 300
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("finished", "succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("arena did not finish")


def test_evoforge_lane_passes_where_the_single_shot_lane_fails(monkeypatch):
    _builder(monkeypatch, _overcount)  # one realistic miscounted diff, the same for both lanes
    a = _run()
    assert a["status"] in ("finished", "succeeded"), a
    evo, single = a["lanes"]["evoforge"], a["lanes"]["single"]
    assert single["heldout"]["passed"] < single["heldout"]["n"] and single["attempts"] == 1
    assert evo["heldout"]["passed"] == evo["heldout"]["n"] == len(_task()["heldout"])
    assert a["verdict"]["winner"] == "evoforge"
    for lane in (evo, single):
        assert isinstance(lane["cost_cents"], int) and lane["cost_cents"] > 0
        assert lane["elapsed_ms"] >= 0 and lane["events"], lane


def test_equal_work_is_a_tie_not_a_rigged_win(monkeypatch):
    _builder(monkeypatch, lambda d: d)  # a correct diff: both lanes must pass
    a = _run()
    assert a["lanes"]["single"]["heldout"]["passed"] == a["lanes"]["single"]["heldout"]["n"]
    assert a["lanes"]["evoforge"]["heldout"]["passed"] == a["lanes"]["evoforge"]["heldout"]["n"]
    assert a["verdict"]["winner"] == "tie"


def test_lane_events_are_ordered_and_show_roles(monkeypatch):
    _builder(monkeypatch, _overcount)
    evs = _run()["lanes"]["evoforge"]["events"]
    assert [e["seq"] for e in evs] == sorted(e["seq"] for e in evs)
    roles = {e.get("role") for e in evs}
    assert {"builder", "runner"} <= roles, roles


def test_no_heldout_code_or_reference_fix_leaks(monkeypatch):
    _builder(monkeypatch, _overcount)
    blob = json.dumps(_run())
    t = _task()
    assert t["reference_fix"] not in blob
    assert all(h["code"] not in blob for h in t["heldout"])


def test_budget_and_validation(monkeypatch):
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "1")
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: pytest.fail("provider called despite cap"))
    assert c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK}).status_code == 402
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    assert c.post("/v1/arena", json={"suite_version": "v2", "task_id": "SV2-NOPE-99"}).status_code == 404
    assert c.get("/v1/arena/arena_missing").status_code == 404


def test_recent_arenas_are_listed(monkeypatch):
    _builder(monkeypatch, _overcount)
    a = _run()
    assert a["arena_id"] in [x["arena_id"] for x in c.get("/v1/arena").json()["arenas"]]
