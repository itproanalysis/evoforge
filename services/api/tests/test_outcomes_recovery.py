"""Outcome registry reset then recovery from durable evidence."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

import main  # noqa: E402
from evoforge import ledger  # noqa: E402
from evoforge import missions as missions_store  # noqa: E402
from evoforge import outcomes as outcomes_store  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)

SHA = "e" * 40


def setup_function(_):
    ledger.reset()
    ledger.configure({"default": 50000})
    missions_store.reset()
    outcomes_store.reset()
    main._evidence.clear()


def test_outcome_survives_registry_reset_via_evidence():
    m = missions_store.create("fix sub", "main")
    for to in ("GENERATED", "REVIEWED", "RAN", "PR_OPENED"):
        missions_store.mark(m["mission_id"], to)
    run_eid = main._store_evidence({"gates": [{"gate": "GH_INTEGRITY", "result": "PASS"}]})
    pr_eid = main._store_evidence({"pr": {"html_url": "https://github.com/o/p/pull/9"}})
    missions_store.attach_evidence(m["mission_id"], run_eid, "run")
    missions_store.attach_evidence(m["mission_id"], pr_eid, "pr")
    r = c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": SHA})
    assert r.status_code == 201, r.text
    outcomes_store.reset()
    body = c.get("/v1/outcomes").json()
    assert [o["mission_id"] for o in body["outcomes"]] == [m["mission_id"]]
    d = c.get("/v1/dashboard").json()
    assert d["validated_improvements"] == 1
    assert d["validated_mission_ids"] == [m["mission_id"]]
