"""Outcome attestation tests (WVI slice): merge closes the chain, dedupe, fail-closed."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import ledger  # noqa: E402
from evoforge import missions as missions_store  # noqa: E402
from evoforge import outcomes as outcomes_store  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)

SHA = "f" * 40


def setup_function(_):
    ledger.reset()
    ledger.configure({"default": 50000})
    missions_store.reset()
    outcomes_store.reset()
    main._evidence.clear()


def _passed_mission():
    m = missions_store.create("fix add", "main")
    missions_store.mark(m["mission_id"], "GENERATED")
    missions_store.mark(m["mission_id"], "REVIEWED")
    missions_store.mark(m["mission_id"], "RAN")
    missions_store.mark(m["mission_id"], "PR_OPENED")
    run_eid = main._store_evidence({"gates": [
        {"gate": "GH_INTEGRITY", "result": "PASS"},
        {"gate": "G2_REQUIRED", "result": "PASS"},
    ]})
    pr_eid = main._store_evidence({"pr": {"html_url": "https://github.com/o/p/pull/1"}})
    missions_store.attach_evidence(m["mission_id"], run_eid, "run")
    missions_store.attach_evidence(m["mission_id"], pr_eid, "pr")
    return m


def test_record_validated_outcome():
    m = _passed_mission()
    r = c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": SHA})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome_status"] == "VALIDATED" and body["weight"] == 1
    assert body["pr_url"] == "https://github.com/o/p/pull/1"
    d = c.get("/v1/dashboard").json()
    assert d["validated_improvements"] == 1
    assert d["validated_mission_ids"] == [m["mission_id"]]


def test_duplicate_is_409():
    m = _passed_mission()
    assert c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": SHA}).status_code == 201
    assert c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": SHA}).status_code == 409


def test_non_pr_mission_is_409():
    m = missions_store.create("x", "main")
    r = c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": SHA})
    assert r.status_code == 409


def test_failing_gates_is_409():
    m = missions_store.create("x", "main")
    for to in ("GENERATED", "REVIEWED", "RAN", "PR_OPENED"):
        missions_store.mark(m["mission_id"], to)
    run_eid = main._store_evidence({"gates": [{"gate": "GH_INTEGRITY", "result": "FAIL"}]})
    pr_eid = main._store_evidence({"pr": {"html_url": "https://github.com/o/p/pull/2"}})
    missions_store.attach_evidence(m["mission_id"], run_eid, "run")
    missions_store.attach_evidence(m["mission_id"], pr_eid, "pr")
    assert c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": SHA}).status_code == 409


def test_bad_sha_and_unknown_mission():
    m = _passed_mission()
    assert c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": "zzz"}).status_code == 409
    assert c.post("/v1/outcomes", json={"mission_id": "msn_nope", "merged_sha": SHA}).status_code == 404


def test_outcomes_list():
    m = _passed_mission()
    c.post("/v1/outcomes", json={"mission_id": m["mission_id"], "merged_sha": SHA})
    body = c.get("/v1/outcomes").json()
    assert [o["mission_id"] for o in body["outcomes"]] == [m["mission_id"]]
