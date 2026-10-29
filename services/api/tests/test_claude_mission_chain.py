"""Claude — external review (release 18): GET /v1/evidence/<run record> showed PR/Outcome empty although the mission's PR
was open, because each record links only the stages known when it was written. mission_chain merges them."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
STAGES = ["ObjectiveVersion", "Task", "Candidate", "Gate", "Review", "PR", "Outcome"]
LINKS = {"ev_obj": {"ObjectiveVersion": "e1"}, "ev_run": {"Candidate": "e3", "Gate": "e4"},
         "ev_pr": {"Candidate": "e3", "Gate": "e4", "PR": "e6"}}


def test_mission_chain_merges_stages_over_the_missions_records(monkeypatch):
    main._evidence["ev_run"] = {"id": "ev_run", "mission_id": "msn_x", "diff": "d"}
    monkeypatch.setattr(main.missions_store, "get",
                        lambda mid: {"evidence_ids": list(LINKS)} if mid == "msn_x" else None)
    monkeypatch.setattr(main.evidence_chain, "chain",
                        lambda eid: [{"stage": s, "event_id": LINKS.get(eid, {}).get(s)} for s in STAGES])
    body = c.get("/v1/evidence/ev_run").json()
    assert {x["stage"]: x["event_id"] for x in body["chain"]}["PR"] is None  # the record itself predates the PR
    merged = {x["stage"]: x["event_id"] for x in body["mission_chain"]}
    assert [x["stage"] for x in body["mission_chain"]] == STAGES
    assert merged == {"ObjectiveVersion": "e1", "Task": None, "Candidate": "e3", "Gate": "e4", "Review": None,
                      "PR": "e6", "Outcome": None}  # an opened PR is not an Outcome
    assert "mission_chain" not in body["data"]


def test_record_without_mission_has_no_mission_chain():
    main._evidence["ev_lone"] = {"id": "ev_lone", "goal": "g"}
    assert "mission_chain" not in c.get("/v1/evidence/ev_lone").json()
