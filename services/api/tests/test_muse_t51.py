"""Builder-side checks for T51 Evolution Rounds (v3.8 P0-A + P0-B)."""
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
from evoforge import broker_meta, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
HEX64 = re.compile(r"^sha256:[0-9a-f]{64}$")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    yield
    end = time.time() + 180
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.2)


def _empty_builder(monkeypatch, calls):
    def fake(goal, sha, file_context=None, **k):
        calls.append(goal)
        return {"diff": "", "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}
    monkeypatch.setattr(broker_meta, "call_builder", fake)
    monkeypatch.setattr(broker_meta, "call_critic",
                        lambda goal, diff, ci="", **k: {"sealed_tests": [], "review": {},
                                                       "stub": False, "usage": {"prompt_tokens": 10,
                                                                                "completion_tokens": 10}})


def _wait(rid):
    end = time.time() + 300
    while time.time() < end:
        d = c.get(f"/v1/evolution/runs/{rid}").json()
        if d.get("status") in ("succeeded", "failed"):
            return d
        time.sleep(0.3)
    pytest.fail("evolution run did not finish")


def test_apps_list_is_redacted(monkeypatch):
    _empty_builder(monkeypatch, [])
    r = c.get("/v1/evolution/apps")
    assert r.status_code == 200
    apps = r.json()["apps"]
    assert apps and apps[0]["app_id"] == "mission_board"
    assert [x["index"] for x in apps[0]["rounds"]] == [1, 2, 3, 4, 5]
    blob = json.dumps(r.json())
    assert "reference" not in blob and "heldout" not in blob and "def test_" not in blob


def test_post_validation_and_budget_guard(monkeypatch):
    calls = []
    _empty_builder(monkeypatch, calls)
    assert c.post("/v1/evolution/runs", json={"app_id": "nope"}).status_code == 404
    assert c.post("/v1/evolution/runs", json={"app_id": "mission_board", "feedback": "bogus"}).status_code == 422
    assert c.post("/v1/evolution/runs", json={"app_id": "mission_board", "rounds": 0}).status_code == 422
    assert c.post("/v1/evolution/runs", json={"app_id": "mission_board", "rounds": 6}).status_code == 422
    assert c.get("/v1/evolution/runs/does-not-exist").status_code == 404
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "10")
    r = c.post("/v1/evolution/runs", json={"app_id": "mission_board", "feedback": "critic", "rounds": 5})
    assert r.status_code == 402, r.text
    assert calls == [], "budget guard must run before any provider call"


def test_empty_diff_round_is_failed_with_preview(monkeypatch):
    calls = []
    _empty_builder(monkeypatch, calls)
    r = c.post("/v1/evolution/runs", json={"app_id": "mission_board", "feedback": "heldout", "rounds": 1})
    assert r.status_code == 202, r.text
    rid = r.json()["run_id"]
    running = c.get(f"/v1/evolution/runs/{rid}").json()
    assert running["status"] == "running"
    assert running["manifest"]["lanes"]["single"]["harness"] == "api-sealed-eval/1"
    assert running["manifest"]["lanes"]["evoforge"]["harness"] == "api-sealed-eval/2"
    done = _wait(rid)
    assert done["status"] == "succeeded"
    sides = done["rounds"][0]["sides"]
    for lane in ("single", "evoforge"):
        snap = sides[lane]
        assert snap["status"] == "FAILED" and snap["verified"] is False
        assert HEX64.match(snap["source_sha"])
        assert snap["heldout"] == {"passed": 0, "n": 3}
        assert snap["round_tests"] == {"passed": 0, "n": 3}
        assert isinstance(snap["preview_html"], str) and snap["preview_html"]
        assert HEX64.match(snap["preview_sha"])
        assert isinstance(snap["diff"], str) and isinstance(snap["attempts"], int)
        assert isinstance(snap["cost_cents"], int) and isinstance(snap["elapsed_ms"], int)
        assert snap["events"] and all(set(e) >= {"seq", "ts", "role", "message"} for e in snap["events"])
    # FAILED rounds keep the base files on both lanes.
    assert sides["single"]["source_sha"] == sides["evoforge"]["source_sha"]
    blob = json.dumps(done)
    assert "def test_" not in blob
    assert done["totals"]["single"]["verified_rounds"] == 0
    row = next(x for x in c.get("/v1/evolution/runs").json()["runs"] if x["run_id"] == rid)
    assert row["status"] == "succeeded"


def test_get_is_read_only_replay(monkeypatch):
    calls = []
    _empty_builder(monkeypatch, calls)
    rid = c.post("/v1/evolution/runs", json={"app_id": "mission_board", "rounds": 1}).json()["run_id"]
    _wait(rid)
    n_calls = len(calls)
    assert n_calls > 0
    c.get(f"/v1/evolution/runs/{rid}")
    c.get("/v1/evolution/runs")
    c.get("/v1/evolution/apps")
    assert len(calls) == n_calls, "GET endpoints must never call a model"
