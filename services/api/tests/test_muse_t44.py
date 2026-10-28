"""Muse T44 arena engine: the same sealed task runs in two lanes at once."""
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
from evoforge import arena as arena_mod  # noqa: E402
from evoforge import broker_meta, commands, eval_jobs, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"


def _v2_task() -> dict:
    directory = sealed_eval.sealed_dir("v2")
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(directory, name), encoding="utf-8") as fh:
            doc = json.load(fh)
        for task in doc.get("tasks", []):
            return arena_mod.find_task("v2", task["id"])
    raise AssertionError("no v2 sealed task found")


TASK = _v2_task()
TASK_ID = TASK["id"]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset()
    ledger.configure({"default": 500000})
    commands.reset()
    eval_jobs.clear()
    arena_mod.clear()
    yield
    _drain(timeout=180)
    eval_jobs.clear()
    arena_mod.clear()
    ledger.reset()
    ledger.configure({"default": 500000})


def _drain(timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get("/v1/arena")
        if r.status_code != 200:
            return
        if not any(a.get("status") == "running" for a in r.json().get("arenas", [])):
            return
        time.sleep(0.5)


def _wait(aid, timeout=300):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = c.get(f"/v1/arena/{aid}")
        assert r.status_code == 200, r.text
        last = r.json()
        assert last["arena_id"] == aid
        if last["status"] in ("succeeded", "failed"):
            return last
        time.sleep(0.5)
    raise AssertionError(f"arena {aid} did not finish: {last}")


def _empty_builder(goal, sha, file_context=None, **k):
    return {"diff": "", "tests": [], "rationale": "x", "stub": False,
            "model": "m", "provider_calls": []}


def _ref_builder(task):
    def builder(goal, sha, file_context=None, **k):
        if task["goal"] in goal or goal in task["goal"]:
            return {"diff": task["reference_fix"], "tests": [], "rationale": "x",
                    "stub": False, "model": "m", "provider_calls": []}
        return _empty_builder(goal, sha)
    return builder


def _corrupt_hunk_counts(diff: str) -> str:
    def _rep(m):
        return f"@@ -{m.group(1)},999 +{m.group(3)},999 @@"

    out = re.sub(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",
                 _rep, diff, count=1)
    assert out != diff
    return out


def _lane_shape(lane):
    assert set(lane) >= {"status", "attempts", "heldout", "outcome",
                         "cost_cents", "elapsed_ms", "diff", "events"}
    assert lane["status"] in ("running", "succeeded", "failed")
    assert isinstance(lane["attempts"], int) and lane["attempts"] >= 0
    assert lane["outcome"] in ("passed", "empty_diff", "apply_failed",
                               "heldout_failed")
    assert set(lane["heldout"]) >= {"passed", "n"}
    assert isinstance(lane["heldout"]["passed"], int)
    assert isinstance(lane["heldout"]["n"], int)
    assert isinstance(lane["cost_cents"], int) and lane["cost_cents"] >= 0
    assert isinstance(lane["elapsed_ms"], int) and lane["elapsed_ms"] >= 0
    assert isinstance(lane["diff"], str)
    assert isinstance(lane["events"], list) and lane["events"]
    seqs = [e["seq"] for e in lane["events"]]
    assert seqs == sorted(seqs)
    for e in lane["events"]:
        assert set(e) >= {"seq", "ts", "role", "message"}
        assert e["role"] in ("builder", "critic", "runner", "gate")
        assert isinstance(e["message"], str) and e["message"]


def test_unknown_task_is_404_and_calls_no_provider(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder",
                        lambda *a, **k: pytest.fail("provider called for unknown task"))
    r = c.post("/v1/arena", json={"suite_version": "v2", "task_id": "NOPE-1"})
    assert r.status_code == 404, r.text
    assert c.get("/v1/arena").json()["arenas"] == []
    assert c.get("/v1/eval/jobs").json()["jobs"] == []


def test_budget_refusal_is_synchronous_402(monkeypatch):
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "1")
    monkeypatch.setattr(broker_meta, "call_builder",
                        lambda *a, **k: pytest.fail("provider called despite cap"))
    before = ledger.snapshot()
    r = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK_ID})
    assert r.status_code == 402, r.text
    assert c.get("/v1/arena").json()["arenas"] == []
    assert c.get("/v1/eval/jobs").json()["jobs"] == []
    after = ledger.snapshot()
    assert after["spent_cents"] == before["spent_cents"]
    assert after["reserved_cents"] == before["reserved_cents"]


def test_empty_builders_tie_with_shape_and_cost(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _empty_builder)
    before = ledger.snapshot()["spent_cents"]
    t0 = time.time()
    r = c.post("/v1/arena", json={"task_id": TASK_ID})
    elapsed = time.time() - t0
    assert r.status_code == 202, r.text
    body = r.json()
    assert re.fullmatch(r"[A-Za-z0-9_\-]{6,80}", body["arena_id"]), body
    assert body["status"] == "running"
    assert elapsed < 30, f"POST blocked for {elapsed:.1f}s; lanes must run in background"
    done = _wait(body["arena_id"])
    assert done["status"] == "succeeded", done
    assert done["suite_version"] == "v2" and done["task_id"] == TASK_ID
    assert done["model"] == "muse-spark-1.3"
    assert set(done["lanes"]) == {"single", "evoforge"}
    single, evo = done["lanes"]["single"], done["lanes"]["evoforge"]
    _lane_shape(single)
    _lane_shape(evo)
    assert single["status"] == "succeeded" and evo["status"] == "succeeded"
    assert single["attempts"] == 1
    assert evo["attempts"] == 3
    assert single["outcome"] == "empty_diff" and evo["outcome"] == "empty_diff"
    assert single["diff"] == "" and evo["diff"] == ""
    assert single["heldout"]["passed"] == 0 and evo["heldout"]["passed"] == 0
    # Usage-free stub calls settle at the per-call maximum, like the evals.
    assert single["cost_cents"] == 120
    assert evo["cost_cents"] == 360
    assert done["verdict"]["winner"] == "tie"
    assert isinstance(done["verdict"]["reason"], str) and done["verdict"]["reason"]
    assert ledger.snapshot()["spent_cents"] - before == 480


def test_strict_single_fails_where_recount_pipeline_passes(monkeypatch):
    bad = _corrupt_hunk_counts(TASK["reference_fix"])

    def builder(goal, sha, file_context=None, **k):
        if TASK["goal"] in goal or goal in TASK["goal"]:
            return {"diff": bad, "tests": [], "rationale": "x",
                    "stub": False, "model": "m", "provider_calls": []}
        return _empty_builder(goal, sha)

    monkeypatch.setattr(broker_meta, "call_builder", builder)
    r = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK_ID})
    assert r.status_code == 202, r.text
    done = _wait(r.json()["arena_id"])
    assert done["status"] == "succeeded", done
    single, evo = done["lanes"]["single"], done["lanes"]["evoforge"]
    assert single["outcome"] == "apply_failed", single
    assert single["attempts"] == 1
    assert evo["outcome"] == "passed", evo
    assert evo["attempts"] == 1
    assert evo["heldout"]["passed"] == evo["heldout"]["n"] > 0
    assert done["verdict"]["winner"] == "evoforge", done["verdict"]
    # The Builder's own output is fine to show.
    assert evo["diff"] == bad


def test_reference_fix_in_both_lanes_is_a_tie(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _ref_builder(TASK))
    r = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK_ID})
    assert r.status_code == 202, r.text
    done = _wait(r.json()["arena_id"])
    assert done["status"] == "succeeded", done
    single, evo = done["lanes"]["single"], done["lanes"]["evoforge"]
    assert single["outcome"] == "passed" and evo["outcome"] == "passed"
    assert single["heldout"]["passed"] == evo["heldout"]["passed"] > 0
    assert done["verdict"]["winner"] == "tie"


def test_only_one_arena_job_runs_at_a_time(monkeypatch):
    gate = threading.Event()

    def slow(goal, sha, file_context=None, **k):
        assert gate.wait(timeout=120), "lane thread was not released"
        return _empty_builder(goal, sha)

    monkeypatch.setattr(broker_meta, "call_builder", slow)
    first = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK_ID})
    assert first.status_code == 202, first.text
    aid = first.json()["arena_id"]
    # While the first arena runs, a second arena (same shared slot) must 409.
    second = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK_ID})
    gate.set()
    assert second.status_code == 409, second.text
    assert aid in second.text
    done = _wait(aid)
    assert done["status"] == "succeeded", done


def test_arena_blocks_eval_jobs_slot(monkeypatch):
    gate = threading.Event()

    def slow(goal, sha, file_context=None, **k):
        assert gate.wait(timeout=120), "lane thread was not released"
        return _empty_builder(goal, sha)

    monkeypatch.setattr(broker_meta, "call_builder", slow)
    first = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK_ID})
    assert first.status_code == 202, first.text
    blocked = c.post("/v1/eval/jobs", json={"kind": "X_SINGLE",
                                            "suite_version": "v2",
                                            "family": "simple_sequential"})
    gate.set()
    assert blocked.status_code == 409, blocked.text
    _wait(first.json()["arena_id"])


def test_unknown_arena_is_404():
    assert c.get("/v1/arena/arena_does_not_exist").status_code == 404


def test_list_is_newest_first(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _empty_builder)
    ids = []
    for _ in range(3):
        r = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK_ID})
        assert r.status_code == 202, r.text
        ids.append(r.json()["arena_id"])
        _wait(ids[-1])
    arenas = c.get("/v1/arena").json()["arenas"]
    assert len(arenas) == 3
    assert [a["arena_id"] for a in arenas] == ids[::-1]
    ats = [a["created_at"] for a in arenas]
    assert ats == sorted(ats, reverse=True)


def test_responses_never_leak_heldout_or_reference_fix(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _empty_builder)
    r = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK_ID})
    aid = r.json()["arena_id"]
    done = _wait(aid)
    blob = r.text + json.dumps(done) + c.get("/v1/arena").text
    assert TASK["reference_fix"] not in blob
    for h in TASK["heldout"]:
        assert h["code"] not in blob


def _read(rel):
    return (WEB / rel).read_text(encoding="utf-8")


def test_proxy_allows_arena_routes():
    src = _read("lib/proxyPolicy.ts")
    assert "/v1/arena" in src
    cases = json.loads(_read("lib/proxyPolicy.cases.json"))
    blob = json.dumps(cases)
    assert "/v1/arena" in blob
    by_path = {tuple(e["path_segments"]): e["expected"] for e in cases}
    assert by_path[("v1", "arena")] == "/v1/arena"
    assert by_path[("v1", "arena", "arena_abc123")] == "/v1/arena/arena_abc123"
