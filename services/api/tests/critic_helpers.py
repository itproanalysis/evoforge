"""Critic test helpers: the held-out suite reaches /v1/runs only via a server-stored review (T10)."""
from __future__ import annotations

KINDS = ("compositional", "negative", "boundary")


def sealed_suite(code: str = "def test_h():\n    assert 1 == 1\n", kinds=KINDS) -> list[dict]:
    return [{"kind": k, "code": code.replace("def test_h", f"def test_h_{k}")} for k in kinds]


def server_review(client, monkeypatch, sealed: list[dict], stub: bool = False) -> str:
    """Store a Critic review whose sealed suite is `sealed`; return its evidence id."""
    from evoforge import broker_meta

    out = {"sealed_tests": sealed, "review": {"result": "PASS", "findings": []}, "stub": stub,
           "execution_verified": False, "model": "muse-spark-1.3"}
    monkeypatch.setattr(broker_meta, "call_critic", lambda *a, **k: dict(out))
    r = client.post("/v1/candidates/review", json={"goal_contract": "spec", "diff": ""})
    assert r.status_code == 200, r.text
    return r.json()["evidence_id"]
