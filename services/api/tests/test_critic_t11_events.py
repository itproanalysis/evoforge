"""Critic acceptance (sealed during build, promoted after) — T11 every chain event id resolves to a real stage summary (finding F2)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from critic_helpers import sealed_suite, server_review  # noqa: E402
from evoforge import commands, github, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
STRONG = [{"code": "def test_value():\n    assert result == 3\n"}]
DIFF = "--- a/src/v.py\n+++ b/src/v.py\n@@ -1 +1 @@\n-result = 2\n+result = 3\n"
MARK = "T11_SEALED_MARK_9013"
REAL = sealed_suite(f"from v import result\n\ndef test_h():\n    assert result == 3  # {MARK}\n")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()
    from evoforge import runner
    monkeypatch.setattr(runner, "run_candidate", lambda *a, **k: {
        "base": "b" * 40, "hygiene": [], "heldout_kinds": [t["kind"] for t in REAL],
        "visible": {"pass": 1, "n": 1, "timed_out": False, "exit_code": 0},
        "heldout": {"pass": 3, "n": 3, "timed_out": False, "exit_code": 0}})
    monkeypatch.setattr(github, "create_pr", lambda *a, **k: {"html_url": "https://github.com/o/r/pull/11"})


def _resolve_all(eid):
    body = c.get(f"/v1/evidence/{eid}").json()
    events = {}
    for link in body["chain"]:
        if link["event_id"] is None:
            continue
        r = c.get(f"/v1/events/{link['event_id']}")
        assert r.status_code == 200, (link, r.text)
        ev = r.json()
        assert ev["id"] == link["event_id"]
        assert (ev.get("stage") or ev.get("kind")) == link["stage"]
        assert ev["evidence_id"] in (eid, body.get("source_evidence_id"), body.get("data", {}).get("source_evidence_id"))
        assert isinstance(ev.get("summary"), dict) and ev["summary"], ev
        assert MARK not in r.text  # held-out code never leaks through an event
        events[link["stage"]] = ev
    return body, events


def test_generate_events_carry_stage_facts():
    out = c.post("/v1/commands/generate", json={"goal": "t11 goal", "idempotency_key": "t11-g"}).json()
    _, ev = _resolve_all(out["evidence"]["id"])
    assert set(ev) == {"Task", "Candidate", "Gate"}
    assert out["command_id"] in repr(ev["Task"]["summary"])
    gates = {g["gate"]: g["result"] for g in out["gates"]}
    assert all(f"'{k}'" in repr(ev["Gate"]["summary"]) or k in repr(ev["Gate"]["summary"]) for k in gates)


def test_run_review_pr_events(monkeypatch):
    rid = server_review(c, monkeypatch, REAL)
    _, rev = _resolve_all(rid)
    assert "Review" in rev and "PASS" in repr(rev["Review"]["summary"])
    run = c.post("/v1/runs", json={"source_repo": "C:/repos/p", "base_sha": "b" * 40, "diff": DIFF,
                                   "tests": STRONG, "review_evidence_id": rid}).json()
    _, runev = _resolve_all(run["evidence_id"])
    assert {"Candidate", "Gate"} <= set(runev)
    assert "3" in repr(runev["Gate"]["summary"]) or "3" in repr(runev["Candidate"]["summary"])  # run counts present
    pr = c.post("/v1/pr/create", json={"evidence_id": run["evidence_id"], "title": "t11"}).json()
    _, prev = _resolve_all(pr["evidence_id"])
    assert "https://github.com/o/r/pull/11" in repr(prev["PR"]["summary"])


def test_objective_event():
    out = c.post("/v1/objectives", json={"goal": "t11 objective goal"}).json()
    _, ev = _resolve_all(out["evidence_id"])
    assert "t11 objective goal" in repr(ev["ObjectiveVersion"]["summary"])


def test_unknown_event_404_and_missing_stages_null():
    assert c.get("/v1/events/ev_000000000000").status_code == 404
    out = c.post("/v1/objectives", json={"goal": "g"}).json()
    body = c.get(f"/v1/evidence/{out['evidence_id']}").json()
    assert [x["event_id"] for x in body["chain"] if x["stage"] != "ObjectiveVersion"] == [None] * 6


def test_evidence_page_drilldown_source():
    web = Path(__file__).resolve().parents[3] / "apps" / "web"
    api = (web / "lib" / "api.ts").read_text(encoding="utf-8")
    page = (web / "app" / "evidence" / "page.tsx").read_text(encoding="utf-8")
    assert "getEvent" in api and "/v1/events/" in api
    assert "getEvent" in page and "증거 부족" in page
