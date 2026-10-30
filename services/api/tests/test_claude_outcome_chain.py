"""Critic (Claude) — a recorded outcome fills the evidence chain's Outcome stage (review B6).

Release 27 stored the outcome of merged PR #7 but never linked the chain's Outcome stage, so the Evidence page still
showed Outcome as missing. A new outcome links it; repeating the same merge repairs an outcome stored unlinked.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import evidence as evidence_chain  # noqa: E402
from evoforge import ledger  # noqa: E402
from evoforge import missions as missions_store  # noqa: E402
from evoforge import outcomes as outcomes_store  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)

SHA = "a" * 40


def setup_function(_):
    ledger.reset()
    ledger.configure({"default": 50000})
    missions_store.reset()
    outcomes_store.reset()
    evidence_chain.clear()
    main._evidence.clear()


def _pr_mission():
    m = missions_store.create("add div", "main")
    for state in ("GENERATED", "REVIEWED", "RAN", "PR_OPENED"):
        missions_store.mark(m["mission_id"], state)
    run_eid = main._store_evidence({"gates": [{"gate": "GH_INTEGRITY", "result": "PASS"}],
                                    "mission_id": m["mission_id"]})
    pr_eid = main._store_evidence({"pr": {"html_url": "https://github.com/o/p/pull/7"},
                                   "mission_id": m["mission_id"]})
    missions_store.attach_evidence(m["mission_id"], run_eid, "run")
    missions_store.attach_evidence(m["mission_id"], pr_eid, "pr")
    return m, pr_eid


def _outcome_stage(eid):
    chain = c.get(f"/v1/evidence/{eid}").json()["mission_chain"]
    return next(e for e in chain if e["stage"] == "Outcome")


def test_recorded_outcome_fills_the_mission_chain():
    m, pr_eid = _pr_mission()
    r = c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": SHA})
    assert r.status_code == 201, r.text
    stage = _outcome_stage(pr_eid)
    assert stage["event_id"], "the PR's mission chain shows the outcome"
    summary = c.get(f"/v1/events/{stage['event_id']}").json()["summary"]
    assert summary["outcome_status"] == "VALIDATED" and summary["merged_sha"] == SHA
    assert summary["pr_url"] == "https://github.com/o/p/pull/7"
    assert c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": SHA}).status_code == 409


def test_outcome_stored_unlinked_is_repaired_once_and_survives_a_restart():
    m, pr_eid = _pr_mission()
    out = {"mission_id": m["mission_id"], "outcome_status": "VALIDATED", "merged_sha": SHA,
           "pr_url": "https://github.com/o/p/pull/7", "weight": 1}
    eid = main._store_evidence({"outcome": out, "mission_id": m["mission_id"]})  # as release 27 left it
    missions_store.attach_evidence(m["mission_id"], eid)
    assert _outcome_stage(pr_eid)["event_id"] is None

    other = c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": "b" * 40})
    assert other.status_code == 409, "a different merge sha never replaces the recorded outcome"
    r = c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": SHA})
    assert r.status_code == 200, r.text
    assert r.json()["evidence_id"] == eid
    assert _outcome_stage(pr_eid)["event_id"]
    assert c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": SHA}).status_code == 409
    assert len(c.get("/v1/outcomes").json()["outcomes"]) == 1
