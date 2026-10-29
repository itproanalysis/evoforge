"""Muse T48 arena fairness manifest: every arena states, before and after
it runs, that both lanes got the same task and the same held-out tests,
and what each lane was allowed."""
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
from evoforge import arena as arena_mod  # noqa: E402
from evoforge import broker_meta, commands, eval_jobs, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


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
        if not any(a.get("status") == "running"
                   for a in r.json().get("arenas", [])):
            return
        time.sleep(0.5)


def _wait(aid, timeout=300):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = c.get(f"/v1/arena/{aid}")
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in ("succeeded", "failed"):
            return last
        time.sleep(0.5)
    raise AssertionError(f"arena {aid} did not finish: {last}")


def _empty_builder(goal, sha, file_context=None, **k):
    return {"diff": "", "tests": [], "rationale": "x", "stub": False,
            "model": "m", "provider_calls": []}


def _expected_spec_hash(task):
    raw = json.dumps({"goal": task["goal"], "files": task["files"]},
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _expected_heldout_hash(task):
    items = [{"id": h["id"], "code": h["code"]} for h in task["heldout"]]
    raw = json.dumps(items, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def test_manifest_states_same_task_same_tests(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _empty_builder)
    doc = arena_mod.seed_running("aid_t48_hash", "v2", TASK_ID,
                                 "muse-spark-1.3", TASK)
    try:
        m = doc["manifest"]
        assert m["comparison_mode"] == "same_task_same_tests_concurrent"
        assert m["suite_version"] == "v2" and m["task_id"] == TASK_ID
        assert m["task_spec_hash"] == _expected_spec_hash(TASK)
        assert m["heldout_hash"] == _expected_heldout_hash(TASK)
        assert m["heldout_count"] == len(TASK["heldout"])
        assert re.fullmatch(r"[0-9a-f]{40}", m["base_tree_sha"]), m
        single, evo = m["lanes"]["single"], m["lanes"]["evoforge"]
        assert single["model"] == "muse-spark-1.3"
        assert single["harness"] == "api-sealed-eval/1"
        assert single["max_attempts"] == 1 and single["critic"] is False
        assert single["feedback"] == "none"
        assert evo["model"] == "muse-spark-1.3"
        assert evo["harness"] == "api-sealed-eval/2"
        assert evo["max_attempts"] == sealed_eval.PIPELINE_MAX_ATTEMPTS
        assert evo["feedback"] == "heldout_failing_test_names"
        assert m["cost_basis"] == "model_api_usage"
        assert m["runner_cost"] == "not_measured"
        assert isinstance(m["disclosure"], str) and m["disclosure"].strip()
        lowered = m["disclosure"].lower()
        assert "failing" in lowered and "held-out" in lowered
        assert "single" in lowered and "runner" in lowered
        assert "upper" in lowered and "bound" in lowered
        assert "oracle" in lowered and "cost" in lowered
        blob = json.dumps(m)
        assert TASK["reference_fix"] not in blob
        assert all(h["code"] not in blob for h in TASK["heldout"])
    finally:
        arena_mod.clear()


def test_base_tree_sha_is_deterministic():
    first = arena_mod.build_manifest("v2", TASK_ID, "muse-spark-1.3", TASK)
    second = arena_mod.build_manifest("v2", TASK_ID, "muse-spark-1.3", TASK)
    assert first["base_tree_sha"] == second["base_tree_sha"]
    assert re.fullmatch(r"[0-9a-f]{40}", first["base_tree_sha"])


def test_manifest_unchanged_from_running_to_finished_and_listed(monkeypatch):
    gate = threading.Event()

    def slow(goal, sha, file_context=None, **k):
        assert gate.wait(timeout=120), "lane thread was not released"
        return _empty_builder(goal, sha)

    monkeypatch.setattr(broker_meta, "call_builder", slow)
    r = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK_ID})
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    running = c.get(f"/v1/arena/{aid}").json()
    assert running["status"] == "running", running
    assert running["manifest"]["task_spec_hash"] == _expected_spec_hash(TASK)
    gate.set()
    done = _wait(aid)
    assert done["status"] == "succeeded", done
    assert done["manifest"] == running["manifest"]
    for lane in (done["lanes"]["single"], done["lanes"]["evoforge"]):
        assert lane["base_tree_sha"] == done["manifest"]["base_tree_sha"]
    rows = c.get("/v1/arena").json()["arenas"]
    row = next(a for a in rows if a["arena_id"] == aid)
    assert row["manifest"] == done["manifest"]
    blob = json.dumps(done) + json.dumps(rows)
    assert TASK["reference_fix"] not in blob
    assert all(h["code"] not in blob for h in TASK["heldout"])
