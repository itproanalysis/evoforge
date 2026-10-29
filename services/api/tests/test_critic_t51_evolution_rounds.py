"""Sealed (Critic) — T51 Evolution Rounds engine (v3.8 P0-A/P0-B, SNAP-01..05/07, ARENA-01/02): one app evolves R1-R5
in two lanes (EvoForge vs single AI) from the same start; every round leaves an immutable snapshot per lane (source
hash, cumulative held-out score, preview, cost, status) and replay is read-only."""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
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
WEB = ROOT / "apps" / "web"
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}


def _round_of(goal):
    m = re.search(r"Round (\d) ", goal or "")
    return int(m.group(1)) if m else 1


def _diff(old, new):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/board.py", "b/board.py"))


def _overcount(diff):
    return re.sub(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@",
                  lambda m: f"@@ -{m.group(1)},{int(m.group(2)) + 1} +{m.group(3)},{int(m.group(4)) + 1} @@", diff,
                  flags=re.M)



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


def _stubs(monkeypatch, overcount_round=None):
    """Builder moves the lane's CURRENT board.py to the round's reference (as a good model would)."""
    def builder(goal, sha, file_context=None, **k):
        n = _round_of(goal)
        current = next(f["content"] for f in (file_context or []) if f["path"] == "board.py")
        d = _diff(current, APP["rounds"][n - 1]["reference"])
        if overcount_round == n:
            d = _overcount(d)
        return {"diff": d, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        n = _round_of(goal)
        return {"sealed_tests": [{"code": h["code"].replace("def test_", "def test_critic_")}
                                 for h in APP["rounds"][n - 1]["heldout"]], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)


def _run(body=None):
    r = c.post("/v1/evolution/runs", json=body or {"app_id": "mission_board"})
    assert r.status_code == 202, r.text
    rid = r.json()["run_id"]
    end = time.time() + 900
    while time.time() < end:
        d = c.get(f"/v1/evolution/runs/{rid}").json()
        if d["status"] in ("succeeded", "failed"):
            return d
        time.sleep(0.5)
    pytest.fail("evolution run did not finish")


def test_both_lanes_evolve_through_five_verified_rounds(monkeypatch):
    _stubs(monkeypatch)
    d = _run()
    assert [r["index"] for r in d["rounds"]] == [1, 2, 3, 4, 5]
    assert [r["name"] for r in d["rounds"]] == [r["name"] for r in APP["rounds"]]
    shas = {"single": [], "evoforge": []}
    for r in d["rounds"]:
        for side in ("single", "evoforge"):
            s = r["sides"][side]
            n_cum = 3 * r["index"]
            assert s["status"] == "READY" and s["verified"] is True, (r["index"], side, s.get("status"))
            assert s["heldout"] == {"passed": n_cum, "n": n_cum}
            assert re.fullmatch(r"sha256:[0-9a-f]{64}", s["source_sha"])
            assert ET.fromstring(s["preview_html"]).get("class") == "board"
            assert isinstance(s["cost_cents"], int) and s["cost_cents"] > 0 and s["elapsed_ms"] >= 0
            shas[side].append(s["source_sha"])
    assert shas["single"] == shas["evoforge"] and len(set(shas["single"])) == 5  # same code, a new version each round
    first = ET.fromstring(d["rounds"][0]["sides"]["evoforge"]["preview_html"])
    last = ET.fromstring(d["rounds"][-1]["sides"]["evoforge"]["preview_html"])
    assert first.find("footer") is None and last.find("footer") is not None


def test_a_failed_round_is_shown_failed_and_never_borrowed(monkeypatch):
    _stubs(monkeypatch, overcount_round=2)  # strict single lane cannot apply R2; EvoForge recounts
    d = _run()
    r1, r2, r3 = d["rounds"][0]["sides"], d["rounds"][1]["sides"], d["rounds"][2]["sides"]
    assert r2["single"]["status"] == "FAILED" and r2["single"]["verified"] is False
    assert r2["single"]["source_sha"] == r1["single"]["source_sha"]  # code unchanged, not copied from the other lane
    assert r2["single"]["source_sha"] != r2["evoforge"]["source_sha"]
    assert r2["evoforge"]["status"] == "READY"
    # R3 starts from the single lane's own (R1) code and catches up: recovery is shown, R2 stays FAILED.
    assert r3["single"]["status"] == "READY" and r3["single"]["source_sha"] == r3["evoforge"]["source_sha"]
    assert d["totals"]["evoforge"]["verified_rounds"] == 5 and d["totals"]["single"]["verified_rounds"] == 4
    assert d["rounds"][1]["sides"]["single"]["heldout"]["passed"] < 6


def test_replay_is_read_only_and_snapshots_do_not_change(monkeypatch):
    _stubs(monkeypatch)
    d = _run()
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: pytest.fail("replay must not call a model"))
    monkeypatch.setattr(broker_meta, "call_critic", lambda *a, **k: pytest.fail("replay must not call a model"))
    again = c.get(f"/v1/evolution/runs/{d['run_id']}").json()
    assert again["rounds"] == d["rounds"]
    listed = c.get("/v1/evolution/runs").json()["runs"]
    assert d["run_id"] in [x["run_id"] for x in listed]


def test_manifest_fixes_the_contract_and_nothing_secret_leaks(monkeypatch):
    _stubs(monkeypatch)
    d = _run({"app_id": "mission_board", "feedback": "critic"})
    m = d["manifest"]
    assert m["app_id"] == "mission_board" and m["rounds"] == 5
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", m["base_sha"])
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", m["heldout_hash"])
    assert m["lanes"]["single"]["max_attempts"] == 1 and m["lanes"]["evoforge"]["feedback"] == "critic"
    assert m["cost_basis"] == "model_api_usage" and isinstance(m["disclosure"], str)
    blob = json.dumps(d)
    for r in APP["rounds"]:
        assert r["reference"] not in blob
        assert all(h["code"] not in blob for h in r["heldout"])


def test_validation_and_budget(monkeypatch):
    assert c.post("/v1/evolution/runs", json={"app_id": "nope"}).status_code == 404
    assert c.post("/v1/evolution/runs", json={"app_id": "mission_board", "rounds": 9}).status_code == 422
    assert c.post("/v1/evolution/runs", json={"app_id": "mission_board", "feedback": "oracle"}).status_code == 422
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "1")
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: pytest.fail("provider called despite cap"))
    assert c.post("/v1/evolution/runs", json={"app_id": "mission_board"}).status_code == 402
    assert c.get("/v1/evolution/runs/evo_missing").status_code == 404
    assert c.get("/v1/evolution/apps").json()["apps"][0]["app_id"] == "mission_board"


def test_proxy_allows_the_evolution_routes():
    policy = (WEB / "lib" / "proxyPolicy.ts").read_text(encoding="utf-8")
    assert "/v1/evolution/runs" in policy and "/v1/evolution/apps" in policy
