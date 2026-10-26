"""Hackathon API tests (pytest + TestClient)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("MODEL_API_KEY", None)
os.environ["EVO_PROJECT_BUDGET_CENTS"] = "50000"

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from evoforge import ledger  # noqa: E402

c = TestClient(app)


def setup_function(_):
    ledger.reset()
    ledger.configure({"default": 50000})


def test_healthz():
    r = c.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"]


def test_generate_stub_inconclusive():
    r = c.post("/v1/commands/generate",
               json={"goal": "fix login", "idempotency_key": "k1"})
    assert r.status_code == 200
    gates = {g["gate"]: g for g in r.json()["gates"]}
    assert gates["GH_INTEGRITY"]["result"] == "INCONCLUSIVE"


def test_review_returns_sealed():
    r = c.post("/v1/candidates/review",
               json={"goal_contract": "login works", "diff": "x", "ci": "ok"})
    assert r.status_code == 200
    assert r.json()["sealed_tests"] and "review" in r.json()


def test_gates_fail_on_tamper():
    r = c.post("/v1/gates/evaluate", json={
        "diff": "--- a/t\n+++ b/t\n@@\n+FIXME_BYPASS\n",
        "tests": [{"code": "def test_a():\n    assert x == 1"}],
        "heldout_kinds": ["compositional", "negative", "extra"],
        "vis_pass": 9, "vis_n": 10, "held_pass": 9, "held_n": 10})
    assert r.status_code == 200
    gates = {g["gate"]: g for g in r.json()["gates"]}
    assert gates["GH_INTEGRITY"]["result"] == "FAIL"


def test_ledger_overdraft_402():
    ledger.reset()
    ledger.configure({"default": 0})
    r = c.post("/v1/commands/generate",
               json={"goal": "x", "idempotency_key": "k2"})
    assert r.status_code == 402


def test_idempotency_same_command():
    r1 = c.post("/v1/commands/generate",
                json={"goal": "same", "idempotency_key": "idem1"})
    r2 = c.post("/v1/commands/generate",
                json={"goal": "same", "idempotency_key": "idem1"})
    assert r1.json()["command_id"] == r2.json()["command_id"]


def test_evidence_roundtrip():
    r = c.post("/v1/objectives", json={"goal": "g"})
    eid = r.json()["evidence_id"]
    assert c.get(f"/v1/evidence/{eid}").status_code == 200
