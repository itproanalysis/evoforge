"""Critic acceptance (sealed during build, promoted after) — T7 evidence chain with stage drilldown (Muse Spark round-3 plan)."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import commands, github, ledger  # noqa: E402
from critic_helpers import sealed_suite, server_review  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
STAGES = ["ObjectiveVersion", "Task", "Candidate", "Gate", "Review", "PR", "Outcome"]
SECRET = "T7_HELDOUT_SECRET_4410"
STRONG = [{"code": "def test_value():\n    assert result == 3\n"}]
DIFF = "--- a/src/v.py\n+++ b/src/v.py\n@@ -1 +1 @@\n-result = 2\n+result = 3\n"
HELD = [{"kind": k, "code": f"# {SECRET}\ndef test_h_{k}():\n    assert 1 == 1\n"}
        for k in ("compositional", "negative", "boundary")]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()
    from evoforge import runner

    def fake(source_repo, base_sha, diff, visible_tests, heldout_tests, timeout_s=120, future_shas=None):
        return {"base": "b" * 40, "hygiene": [],
                "visible": {"pass": 1, "n": 1, "timed_out": False, "exit_code": 0},
                "heldout": {"pass": 3, "n": 3, "timed_out": False, "exit_code": 0},
                "heldout_kinds": [str(t.get("kind", "")) for t in heldout_tests]}

    monkeypatch.setattr(runner, "run_candidate", fake)


def _chain(eid):
    r = c.get(f"/v1/evidence/{eid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == eid and isinstance(body["data"], dict)
    chain = body["chain"]
    assert [x["stage"] for x in chain] == STAGES
    return body, {x["stage"]: x["event_id"] for x in chain}


def _ev_id(x):
    return isinstance(x, str) and re.fullmatch(r"ev_[0-9a-f]{12}", x) is not None


def test_generate_links_task_candidate_gate_only():
    out = c.post("/v1/commands/generate", json={"goal": "t7 gen", "idempotency_key": "t7-gen"}).json()
    body, ch = _chain(out["evidence"]["id"])
    assert all(_ev_id(ch[s]) for s in ("Task", "Candidate", "Gate"))
    assert ch["ObjectiveVersion"] is None and ch["Review"] is None and ch["PR"] is None and ch["Outcome"] is None


def test_objective_links_objective_version():
    out = c.post("/v1/objectives", json={"goal": "t7 obj"}).json()
    _, ch = _chain(out["evidence_id"])
    assert _ev_id(ch["ObjectiveVersion"])
    assert all(ch[s] is None for s in STAGES if s != "ObjectiveVersion")


def test_review_links_review():
    out = c.post("/v1/candidates/review", json={"goal_contract": "t7 spec", "diff": "d"}).json()
    _, ch = _chain(out["evidence_id"])
    assert _ev_id(ch["Review"])


def test_run_then_pr_chain(monkeypatch):
    monkeypatch.setattr(github, "create_pr", lambda *a, **k: {"html_url": "https://github.com/o/r/pull/77"})
    if hasattr(main, "create_pr"):
        monkeypatch.setattr(main, "create_pr", lambda *a, **k: {"html_url": "https://github.com/o/r/pull/77"})
    review = server_review(c, monkeypatch, HELD)
    run = c.post("/v1/runs", json={"source_repo": "C:/repos/p", "base_sha": "b" * 40, "diff": DIFF,
                                   "tests": STRONG, "review_evidence_id": review})
    assert run.status_code == 200, run.text
    src = run.json()["evidence_id"]
    sbody, sch = _chain(src)
    assert _ev_id(sch["Candidate"]) and _ev_id(sch["Gate"])
    assert all(g["result"] == "PASS" for g in run.json()["gates"]), run.json()["gates"]
    pr = c.post("/v1/pr/create", json={"evidence_id": src, "title": "t7"})
    assert pr.status_code == 200, pr.text
    pbody, pch = _chain(pr.json()["evidence_id"])
    assert _ev_id(pch["PR"])
    assert pbody["data"].get("source_evidence_id") == src
    _, sch_after = _chain(src)
    # the PR must stay connected to the run's Candidate/Gate: either the PR record carries them,
    # or the source record gained the PR link
    assert (pch["Candidate"] == sch["Candidate"] and pch["Gate"] == sch["Gate"]) or sch_after["PR"] == pch["PR"]
    assert SECRET not in repr(pbody) and SECRET not in repr(sbody) and SECRET not in run.text


def test_existing_payload_fields_stay_top_level():
    out = c.post("/v1/gates/evaluate", json={"diff": DIFF, "tests": STRONG, "heldout_kinds": [],
                                            "vis_pass": 1, "vis_n": 1, "held_pass": 1, "held_n": 1}).json()
    body = c.get(f"/v1/evidence/{out['evidence_id']}").json()
    assert body["diff"] == DIFF and body["gates"] == out["gates"]
    assert body["data"]["diff"] == DIFF and "chain" in body


def test_unknown_evidence_404():
    assert c.get("/v1/evidence/ev_000000000000").status_code == 404
    assert c.get("/v1/evidence/nope").status_code == 404


def test_event_ids_unique_and_chain_append_only():
    a = c.post("/v1/commands/generate", json={"goal": "t7 a", "idempotency_key": "t7-a"}).json()
    b = c.post("/v1/commands/generate", json={"goal": "t7 b", "idempotency_key": "t7-b"}).json()
    _, ca = _chain(a["evidence"]["id"])
    _, cb = _chain(b["evidence"]["id"])
    ids = [v for v in list(ca.values()) + list(cb.values()) if v]
    assert len(ids) == len(set(ids))
    _, ca2 = _chain(a["evidence"]["id"])
    assert ca2 == ca  # re-reading never rewrites links
    from evoforge import evidence
    with pytest.raises(Exception):
        evidence.link(a["evidence"]["id"], "NotAStage", "ev_0123456789ab")
