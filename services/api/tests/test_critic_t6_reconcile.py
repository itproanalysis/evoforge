"""Critic acceptance (sealed during build, promoted after) — T6 UNKNOWN reservation reconciliation from receipts."""
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

c = TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def fresh():
    ledger.reset()
    ledger.configure({"default": 50000})
    yield
    ledger.reset()


def _unknown(cents=120):
    rid = ledger.reserve(cents)
    ledger.mark_unknown(rid, "timeout")
    return rid


def test_not_billed_releases():
    rid = _unknown()
    out = ledger.reconcile(rid, None)
    assert out["state"] == "REFUNDED" and out["reservation_id"] == rid
    s = ledger.snapshot()
    assert s["reserved_cents"] == 0 and s["spent_cents"] == 0 and s["unknown_reservations"] == []


def test_billed_settles_with_request_id():
    rid = _unknown(120)
    out = ledger.reconcile(rid, 87, "req_abc")
    assert out == {"reservation_id": rid, "state": "SETTLED", "billed_cents": 87, "request_id": "req_abc"}
    s = ledger.snapshot()
    assert s["reserved_cents"] == 0 and s["spent_cents"] == 87 and s["unknown_reservations"] == []


@pytest.mark.parametrize("billed,req", [(10, None), (10, ""), (-1, "r"), (True, "r"), (1.5, "r")])
def test_billed_rules(billed, req):
    rid = _unknown()
    with pytest.raises(ValueError):
        ledger.reconcile(rid, billed, req)
    assert ledger.snapshot()["unknown_reservations"] == [rid]  # untouched on refusal


def test_only_unknown_reservations():
    rid = ledger.reserve(5)
    with pytest.raises(ValueError):
        ledger.reconcile(rid, None)
    with pytest.raises(KeyError):
        ledger.reconcile("rsv_nope", None)
    u = _unknown()
    ledger.reconcile(u, None)
    with pytest.raises(ValueError):
        ledger.reconcile(u, None)


def test_overrun_marked_when_billed_above_budget():
    ledger.reset()
    ledger.configure({"default": 100})
    rid = _unknown(100)
    ledger.reconcile(rid, 150, "req_big")
    assert ledger.snapshot()["overruns"]


def test_api_reconcile_and_snapshot():
    rid = _unknown()
    r = c.post("/v1/ledger/reconcile", json={"reservation_id": rid, "billed_cents": 99, "request_id": "req_1"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["state"] == "SETTLED" and j["evidence_id"]
    assert c.get(f"/v1/evidence/{j['evidence_id']}").status_code == 200
    snap = c.get("/v1/ledger").json()
    assert snap["spent_cents"] == 99 and snap["unknown_reservations"] == []


def test_api_errors():
    assert c.post("/v1/ledger/reconcile", json={"reservation_id": "rsv_x", "billed_cents": None}).status_code == 404
    rid = ledger.reserve(5)
    assert c.post("/v1/ledger/reconcile", json={"reservation_id": rid, "billed_cents": None}).status_code == 409
    u = _unknown()
    assert c.post("/v1/ledger/reconcile", json={"reservation_id": u, "billed_cents": 5}).status_code == 409
    assert c.post("/v1/ledger/reconcile", json={"reservation_id": u, "billed_cents": "5", "request_id": "r"}).status_code == 422
    assert c.post("/v1/ledger/reconcile", json={"reservation_id": u, "billed_cents": -1, "request_id": "r"}).status_code == 422
    assert c.post("/v1/ledger/reconcile", json={"reservation_id": u, "billed_cents": None}).status_code == 200
