"""Sealed (Critic) — T70 signed Arena results: a finished comparison gets one Ed25519 certificate over its fairness
manifest, both lanes' scores, costs, attempts, code and preview digests and the verdict — so a published comparison
(e.g. in the demo video) can be checked offline; any edited field fails; no code or held-out test is in it."""
from __future__ import annotations

import base64
import copy
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
from evoforge import broker_meta, ledger, proof, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
KEY = base64.b64encode(bytes(range(32))).decode()
TASK = "SV2-SS-01"


def _settle(limit=300):
    end = time.time() + limit
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    _settle()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", KEY)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    t = next(x for s in sealed_eval.load_suites("v2") for x in s["tasks"] if x["id"] == TASK)
    monkeypatch.setattr(broker_meta, "call_builder", lambda goal, sha, file_context=None, **k: {
        "diff": t["reference_fix"], "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
        "provider_calls": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}})
    yield t
    _settle()


def _arena():
    r = c.post("/v1/arena", json={"suite_version": "v2", "task_id": TASK})
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    end = time.time() + 300
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("arena did not finish")


def test_finished_arena_gets_one_signed_certificate(fresh):
    a = _arena()
    r = c.get(f"/v1/arena/{a['arena_id']}/proof")
    assert r.status_code == 200, r.text
    cert = r.json()
    assert cert["kind"] == "arena" and cert["arena_id"] == a["arena_id"]
    assert cert["signed"] is True and cert["algorithm"] == "Ed25519" and cert["verify"]["ok"] is True
    assert cert["verdict"] == a["verdict"]["winner"]
    assert cert["manifest"]["task_spec_hash"] == a["manifest"]["task_spec_hash"]
    for side in ("single", "evoforge"):
        lane = cert["lanes"][side]
        assert lane["heldout"] == a["lanes"][side]["heldout"] and lane["cost_cents"] == a["lanes"][side]["cost_cents"]
        assert re.fullmatch(r"[0-9a-f]{64}", lane["diff_sha256"])
    again = c.get(f"/v1/arena/{a['arena_id']}/proof").json()
    assert again["certificate_id"] == cert["certificate_id"] and again["signature"] == cert["signature"]  # stored once
    by_id = c.get(f"/v1/proof/cert/{cert['certificate_id']}").json()
    assert by_id["certificate_id"] == cert["certificate_id"] and by_id["verify"]["ok"] is True


def test_edited_certificate_fails_and_no_code_inside(fresh):
    a = _arena()
    cert = c.get(f"/v1/arena/{a['arena_id']}/proof").json()
    body = {k: v for k, v in cert.items() if k != "verify"}
    assert proof.verify(body)["ok"] is True
    forged = copy.deepcopy(body)
    forged["lanes"]["single"]["heldout"]["passed"] = forged["lanes"]["single"]["heldout"]["n"] + 1
    assert proof.verify(forged)["ok"] is False
    forged = copy.deepcopy(body)
    forged["verdict"] = "single" if body["verdict"] != "single" else "evoforge"
    assert proof.verify(forged)["ok"] is False
    blob = json.dumps(cert)
    assert fresh["reference_fix"] not in blob and all(h["code"] not in blob for h in fresh["heldout"])
    assert "diff" not in cert["lanes"]["single"] and "preview_html" not in cert["lanes"]["single"]


def test_unknown_or_running_arenas_have_no_certificate():
    assert c.get("/v1/arena/arena_missing/proof").status_code == 404
    cases = json.loads((Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "proxyPolicy.cases.json")
                       .read_text(encoding="utf-8"))
    assert any(cs.get("expected") and cs["path_segments"][:2] == ["v1", "arena"] and cs["path_segments"][-1] == "proof"
               and len(cs["path_segments"]) == 4 for cs in cases), "proxy must allow GET /v1/arena/<id>/proof"
