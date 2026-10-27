"""Critic acceptance (sealed during build, promoted after) — T19 run chain links the Review stage; footer tells the truth about costs."""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from critic_helpers import sealed_suite, server_review  # noqa: E402
from evoforge import commands, github, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
MARK = "T19_SEALED_MARK_3131"
DIFF = "--- a/src/v.py\n+++ b/src/v.py\n@@ -1 +1 @@\n-result = 2\n+result = 3\n"
STRONG = [{"code": "def test_value():\n    assert result == 3\n"}]
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()
    from evoforge import runner
    monkeypatch.setattr(runner, "run_candidate", lambda *a, **k: {
        "base": "b" * 40, "hygiene": [], "heldout_kinds": ["compositional", "negative", "boundary"],
        "visible": {"pass": 1, "n": 1, "timed_out": False, "exit_code": 0},
        "heldout": {"pass": 3, "n": 3, "timed_out": False, "exit_code": 0}})
    import evoforge.repo_source as rs
    monkeypatch.setattr(rs, "resolve_repo_dir", lambda *a, **k: tempfile.mkdtemp(prefix="evoforge-remote-test-"))
    if hasattr(main, "resolve_repo_dir"):
        monkeypatch.setattr(main, "resolve_repo_dir", lambda *a, **k: tempfile.mkdtemp(prefix="evoforge-remote-test-"))
    monkeypatch.setattr(github, "create_pr", lambda *a, **k: {"html_url": "https://github.com/o/r/pull/19"})


def _chain(eid):
    body = c.get(f"/v1/evidence/{eid}").json()
    return {x["stage"]: x["event_id"] for x in body["chain"]}


def _run(rid):
    return c.post("/v1/runs", json={"source_repo": "", "base_sha": "b" * 40, "diff": DIFF, "tests": STRONG,
                                    "review_evidence_id": rid})


def test_run_chain_links_the_reviews_review_event(monkeypatch):
    rid = server_review(c, monkeypatch, sealed_suite(f"def test_h():\n    assert 1 == 1  # {MARK}\n"))
    review_event = _chain(rid)["Review"]
    assert review_event
    r = _run(rid)
    assert r.status_code == 200, r.text
    run_chain = _chain(r.json()["evidence_id"])
    assert run_chain["Review"] == review_event
    assert run_chain["Candidate"] and run_chain["Gate"]
    ev = c.get(f"/v1/events/{review_event}")
    assert ev.status_code == 200 and (ev.json().get("stage") or ev.json().get("kind")) == "Review"
    assert MARK not in ev.text
    pr = c.post("/v1/pr/create", json={"evidence_id": r.json()["evidence_id"], "title": "t"})
    assert pr.status_code == 200, pr.text
    assert _chain(pr.json()["evidence_id"])["Review"] == review_event


def test_review_evidence_not_mutated_by_runs(monkeypatch):
    rid = server_review(c, monkeypatch, sealed_suite())
    before = c.get(f"/v1/evidence/{rid}").json()
    _run(rid)
    _run(rid)
    after = c.get(f"/v1/evidence/{rid}").json()
    assert {x["stage"]: x["event_id"] for x in before["chain"]} == {x["stage"]: x["event_id"] for x in after["chain"]}


def test_stub_review_still_409_and_no_run_evidence():
    stub = c.post("/v1/candidates/review", json={"goal_contract": "g", "diff": ""}).json()
    n = len(main._evidence)
    r = _run(stub["evidence_id"])
    assert r.status_code == 409
    assert len(main._evidence) == n


def test_footer_states_real_ledger():
    layout = (WEB / "app" / "layout.tsx").read_text(encoding="utf-8")
    assert "추정치" not in layout and not re.search(r"estimat", layout, re.I)
    assert "ledger" in layout.lower() or "원장" in layout


# ---- Critic additions from the T18 review: missions and endpoints must share one implementation ----

def test_mission_run_chain_links_review_too(monkeypatch):
    from evoforge import broker_meta
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: {
        "diff": DIFF, "tests": STRONG, "rationale": "r", "stub": False, "model": "m", "provider_calls": []})
    monkeypatch.setattr(broker_meta, "call_critic", lambda *a, **k: {
        "sealed_tests": sealed_suite(), "review": {"result": "PASS", "findings": []},
        "stub": False, "execution_verified": False, "model": "m"})
    import evoforge.repo_source as rs
    monkeypatch.setattr(rs, "resolve_ref_to_sha", lambda *a, **k: "b" * 40, raising=False)
    if hasattr(main, "_resolve_mission_base"):
        monkeypatch.setattr(main, "_resolve_mission_base", lambda ref: "b" * 40)
    mid = c.post("/v1/missions", json={"goal": "g", "repo_ref": "b" * 40, "risk": "LOW"}).json()["mission_id"]
    for to in ("GENERATED", "REVIEWED", "RAN"):
        r = c.post(f"/v1/missions/{mid}/advance", json={"to": to})
        assert r.status_code == 200, (to, r.text)
    m = c.get(f"/v1/missions/{mid}").json()
    blob = str(m)
    review_ids = [e for e in main._evidence if main._evidence[e].get("mission_id") == mid and "review" in main._evidence[e]]
    run_ids = [e for e in main._evidence if main._evidence[e].get("mission_id") == mid and "run" in main._evidence[e]]
    assert review_ids and run_ids, blob
    assert _chain(run_ids[-1])["Review"] == _chain(review_ids[-1])["Review"]


def test_mission_never_runs_candidates_in_process_when_runner_configured(monkeypatch):
    from evoforge import broker_meta, runner
    monkeypatch.setenv("EVO_RUNNER_URL", "http://127.0.0.1:9")  # configured but unreachable
    called = []
    monkeypatch.setattr(runner, "run_candidate", lambda *a, **k: called.append(1) or pytest.fail("in-process run"))
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: {
        "diff": DIFF, "tests": STRONG, "rationale": "r", "stub": False, "model": "m", "provider_calls": []})
    monkeypatch.setattr(broker_meta, "call_critic", lambda *a, **k: {
        "sealed_tests": sealed_suite(), "review": {"result": "PASS", "findings": []},
        "stub": False, "execution_verified": False, "model": "m"})
    if hasattr(main, "_resolve_mission_base"):
        monkeypatch.setattr(main, "_resolve_mission_base", lambda ref: "b" * 40)
    mid = c.post("/v1/missions", json={"goal": "g", "repo_ref": "b" * 40, "risk": "LOW"}).json()["mission_id"]
    c.post(f"/v1/missions/{mid}/advance", json={"to": "GENERATED"})
    c.post(f"/v1/missions/{mid}/advance", json={"to": "REVIEWED"})
    r = c.post(f"/v1/missions/{mid}/advance", json={"to": "RAN"})
    assert called == []  # the invariant: never execute candidate code in the API process
    assert r.status_code in (400, 502), r.text  # bundle/runner failure mapping, as POST /v1/runs
