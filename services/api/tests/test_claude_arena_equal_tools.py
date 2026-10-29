"""Claude — sealed Arena equal tools (production 2026-10-30): on sealed v5 the single lane lost matches only because its
patch failed the strict hunk-count rule the EvoForge lane does not face. single_apply="tolerant" gives both lanes the
same tolerant recount and the manifest says so; the default stays "strict" for comparisons already on record."""
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
TASK = "SV2-SS-01"


def _miscounted(diff: str) -> str:
    """Same change, wrong hunk line counts: strict apply rejects it, tolerant recount applies it."""
    return re.sub(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@",
                  lambda m: f"@@ -{m[1]},{int(m[2]) + 2} +{m[3]},{int(m[4]) + 3} @@", diff, count=1)


def _settle(limit=300):
    end = time.time() + limit
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    _settle()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    t = next(x for s in sealed_eval.load_suites("v2") for x in s["tasks"] if x["id"] == TASK)
    bad = _miscounted(t["reference_fix"])
    assert bad != t["reference_fix"]
    monkeypatch.setattr(broker_meta, "call_builder", lambda goal, sha, file_context=None, **k: {
        "diff": bad, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
        "provider_calls": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}})
    yield t
    _settle()


def _arena(body):
    r = c.post("/v1/arena", json=body)
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    end = time.time() + 300
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("arena did not finish")


def test_tolerant_single_lane_applies_the_same_miscounted_patch(stubs):
    a = _arena({"suite_version": "v2", "task_id": TASK, "single_apply": "tolerant"})
    s, e = a["lanes"]["single"], a["lanes"]["evoforge"]
    assert s["outcome"] != "apply_failed" and s["heldout"]["passed"] == s["heldout"]["n"] > 0
    assert e["heldout"]["passed"] == e["heldout"]["n"]
    m = a["manifest"]["lanes"]["single"]
    assert m["apply"] == "tolerant" and m["harness"] == "api-sealed-eval/2"
    assert "Equal tools" in a["manifest"]["disclosure"] and a["single_apply"] == "tolerant"
    assert a["verdict"]["winner"] == "tie"


def test_default_strict_is_unchanged(stubs):
    a = _arena({"suite_version": "v2", "task_id": TASK})
    assert a["lanes"]["single"]["outcome"] == "apply_failed"
    assert a["manifest"]["lanes"]["single"]["harness"] == "api-sealed-eval/1"
    assert a["manifest"]["lanes"]["single"]["apply"] == "strict" and "Equal tools" not in a["manifest"]["disclosure"]
