"""Builder self-check for T11 resolvable chain events (non-sealed)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import commands, evidence as evidence_chain, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
SECRET = "T11_BUILDER_SELFCHECK_SECRET"


def setup_function(_):
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()
    evidence_chain.clear()
    main._evidence.clear()


def test_chain_events_resolve_with_summaries():
    out = c.post("/v1/commands/generate", json={"goal": "t11 selfcheck", "idempotency_key": "t11-self"}).json()
    eid = out["evidence"]["id"]
    body = c.get(f"/v1/evidence/{eid}").json()
    assert [x["stage"] for x in body["chain"]] == list(evidence_chain.EVIDENCE_STAGES)
    for entry in body["chain"]:
        ev_id = entry["event_id"]
        if ev_id is None:
            continue
        r = c.get(f"/v1/events/{ev_id}")
        assert r.status_code == 200, r.text
        view = r.json()
        assert view["id"] == ev_id
        assert view["stage"] == entry["stage"] and view["kind"] == entry["stage"]
        assert view["evidence_id"] == eid
        assert isinstance(view["summary"], dict)
        assert SECRET not in repr(view) and SECRET not in repr(body)
    assert c.get("/v1/events/ev_000000000000").status_code == 404


def test_review_event_hides_sealed_code(monkeypatch):
    from evoforge import broker_meta

    sealed = [
        {"kind": "compositional", "code": f"# {SECRET}\ndef test_a():\n    assert 1 == 1\n"},
        {"kind": "negative", "code": f"# {SECRET}\ndef test_b():\n    assert 1 == 1\n"},
        {"kind": "boundary", "code": f"# {SECRET}\ndef test_c():\n    assert 1 == 1\n"},
    ]
    out = {"sealed_tests": sealed, "review": {"result": "PASS", "findings": []},
           "stub": False, "model": "muse-spark-1.3"}
    monkeypatch.setattr(broker_meta, "call_critic", lambda *a, **k: dict(out))
    rev = c.post("/v1/candidates/review", json={"goal_contract": "spec", "diff": ""}).json()
    body = c.get(f"/v1/evidence/{rev['evidence_id']}").json()
    assert SECRET not in repr(body)
    for entry in body["chain"]:
        if entry["event_id"] is None:
            continue
        view = c.get(f"/v1/events/{entry['event_id']}").json()
        assert SECRET not in repr(view)
        assert view["summary"].get("result") == "PASS"
