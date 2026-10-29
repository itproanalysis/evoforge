"""Muse T59: Arena manifest previews + critic-feedback UI contract (web-only).

The API (T48/T49/T50) already returns ``manifest``,
``lanes.*.preview_source/preview_html/preview_error``, and POST /v1/arena
accepts suite_version v1..v4 with feedback "heldout"|"critic". These tests
pin the server side of that contract without running provider-backed arenas.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import arena as arena_mod  # noqa: E402
from evoforge import eval_jobs, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
HEX64 = re.compile(r"^sha256:[0-9a-f]{64}$")
SAMPLES = [("v1", "SV1-AO-01"), ("v2", "SV2-SS-01"),
           ("v3", "SV3-AO-01"), ("v4", "SV4-SS-01")]


@pytest.fixture(autouse=True)
def fresh():
    ledger.reset()
    ledger.configure({"default": 500000})
    eval_jobs.clear()
    arena_mod.clear()
    yield
    eval_jobs.clear()
    arena_mod.clear()
    ledger.reset()
    ledger.configure({"default": 500000})


def test_find_task_covers_v1_through_v4():
    for suite, tid in SAMPLES:
        task = arena_mod.find_task(suite, tid)
        assert task["id"] == tid and task["goal"]
        assert isinstance(task["files"], dict) and task["files"]


def test_manifest_records_feedback_mode_per_lane():
    task = arena_mod.find_task("v2", "SV2-SS-01")
    for mode, lane_feedback in (("heldout", "heldout_failing_test_names"),
                                ("critic", "critic")):
        m = arena_mod.build_manifest("v2", "SV2-SS-01",
                                     "muse-spark-1.3", task, feedback=mode)
        assert HEX64.match(m["task_spec_hash"])
        assert HEX64.match(m["heldout_hash"])
        assert re.fullmatch(r"[0-9a-f]{40}", m["base_tree_sha"])
        assert m["lanes"]["single"] == {**m["lanes"]["single"],
                                        "harness": "api-sealed-eval/1",
                                        "max_attempts": 1, "feedback": "none"}
        assert m["lanes"]["evoforge"]["harness"] == "api-sealed-eval/2"
        assert m["lanes"]["evoforge"]["feedback"] == lane_feedback
        assert isinstance(m["disclosure"], str) and len(m["disclosure"]) >= 40
        blob = json.dumps(m)
        assert task["reference_fix"] not in blob
        assert all(h["code"] not in blob for h in task["heldout"])


def test_seed_running_carries_manifest_and_preview_placeholders():
    task = arena_mod.find_task("v2", "SV2-SS-01")
    doc = arena_mod.seed_running("aid_t59_seed", "v2", "SV2-SS-01",
                                 "muse-spark-1.3", task, feedback="critic")
    try:
        assert doc["feedback"] == "critic"
        assert doc["manifest"]["lanes"]["evoforge"]["feedback"] == "critic"
        for lane in ("single", "evoforge"):
            assert doc["lanes"][lane]["preview_source"] == "none"
    finally:
        arena_mod.clear()


def test_post_arena_rejects_bad_feedback_suite_and_task():
    assert c.post("/v1/arena", json={
        "suite_version": "v2", "task_id": "SV2-SS-01",
        "feedback": "oracle"}).status_code == 422
    assert c.post("/v1/arena", json={
        "suite_version": "v9", "task_id": "SV2-SS-01"}).status_code == 422
    assert c.post("/v1/arena", json={
        "suite_version": "v3", "task_id": "SV3-NOPE-99"}).status_code == 404


def test_lane_preview_runs_on_base_without_provider():
    task = arena_mod.find_task("v4", "SV4-SS-01")
    out = arena_mod._compute_lane_preview(task, "", False, True)
    assert out["preview_source"] == "base"
    assert isinstance(out.get("preview_html"), str) and out["preview_html"]
