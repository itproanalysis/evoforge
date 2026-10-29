"""Sealed (Critic) — T60 equal-tools comparison (v3.8 §4.1 "same tool access"): an evolution run can give the single AI
the same tolerant patch application EvoForge uses, so any remaining gap comes from Critic + retries, not from diff
bookkeeping. The mode is fixed in the manifest; strict stays the default for continuity with recorded runs."""
from __future__ import annotations

import difflib
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
from evoforge import broker_meta, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
ROOT = Path(__file__).resolve().parents[3]
APP = json.loads((ROOT / "evals" / "rounds_v1" / "mission_board.json").read_text(encoding="utf-8"))
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}


def _settle(limit=300):
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


def _round_of(goal):
    m = re.search(r"Round (\d) ", goal or "")
    return int(m.group(1)) if m else 1


def _overcount(diff):
    return re.sub(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@",
                  lambda m: f"@@ -{m.group(1)},{int(m.group(2)) + 1} +{m.group(3)},{int(m.group(4)) + 1} @@", diff,
                  flags=re.M)


def _stubs(monkeypatch):
    def builder(goal, sha, file_context=None, **k):
        n = _round_of(goal)
        current = next(f["content"] for f in (file_context or []) if f["path"] == "board.py")
        d = "".join(difflib.unified_diff(current.splitlines(True), APP["rounds"][n - 1]["reference"].splitlines(True),
                                         "a/board.py", "b/board.py"))
        return {"diff": _overcount(d), "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}  # every diff miscounts its hunks, as models often do

    def critic(goal, diff, ci="", **k):
        n = _round_of(goal)
        return {"sealed_tests": [{"code": h["code"].replace("def test_", "def test_critic_")}
                                 for h in APP["rounds"][n - 1]["heldout"]], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)


def _run(body):
    r = c.post("/v1/evolution/runs", json=body)
    assert r.status_code == 202, r.text
    rid = r.json()["run_id"]
    end = time.time() + 900
    while time.time() < end:
        d = c.get(f"/v1/evolution/runs/{rid}").json()
        if d["status"] in ("succeeded", "failed"):
            return d
        time.sleep(0.5)
    pytest.fail("evolution run did not finish")


def test_tolerant_single_lane_applies_the_same_diffs(monkeypatch):
    _stubs(monkeypatch)
    d = _run({"app_id": "mission_board", "rounds": 2, "single_apply": "tolerant"})
    for i in range(2):
        assert d["rounds"][i]["sides"]["single"]["status"] == "READY", i
    m = d["manifest"]["lanes"]["single"]
    assert m["harness"] == "api-sealed-eval/2" and m["apply"] == "tolerant" and m["max_attempts"] == 1
    assert d["manifest"]["lanes"]["evoforge"]["apply"] == "tolerant"
    assert "single_apply" in json.dumps(d["manifest"]) or d["manifest"].get("comparison") == "equal_tools"


def test_strict_stays_the_default(monkeypatch):
    _stubs(monkeypatch)
    d = _run({"app_id": "mission_board", "rounds": 1})
    assert d["rounds"][0]["sides"]["single"]["status"] == "FAILED"  # miscounted hunks do not apply strictly
    assert d["manifest"]["lanes"]["single"]["harness"] == "api-sealed-eval/1"
    assert d["manifest"]["lanes"]["single"]["apply"] == "strict"


def test_bad_mode_rejected_and_stats_split_by_mode(monkeypatch):
    assert c.post("/v1/evolution/runs", json={"app_id": "mission_board", "single_apply": "lenient"}).status_code == 422
    assert c.get("/v1/evolution/stats", params={"single_apply": "tolerant"}).status_code == 200
    assert c.get("/v1/evolution/stats", params={"single_apply": "bogus"}).status_code == 422
