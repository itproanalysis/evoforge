"""Muse T37 durable harness decisions."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import decisions  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def fresh():
    decisions.clear()
    yield
    decisions.clear()


def _doc(i, ts=None):
    return {
        "decision_id": f"dec_t37_{i}",
        "created_at": ts if ts is not None else 1000.0 + i,
        "suite_version": "v2",
        "kind": "X_SINGLE",
        "model": "muse-spark-1.3",
        "family": "simple_sequential",
        "champion": "api-sealed-eval/1",
        "challenger": "api-sealed-eval/2",
        "verdict": "keep",
        "decision": "keep",
        "reason": "no_clear_difference: intervals overlap",
    }


def test_record_persists_in_evidence_store():
    d = _doc(1)
    out = decisions.record(d)
    assert out["decision_id"] == d["decision_id"]
    stored = main._evidence.get(d["decision_id"])
    assert stored["kind"] == "harness_decision"
    assert stored["decision"]["decision_id"] == d["decision_id"]
    assert stored["decision"]["kind"] == "X_SINGLE"
    assert c.get("/v1/eval/decisions").json()["decisions"][0]["decision_id"] == d["decision_id"]


def test_list_newest_first_and_survives_process_memory_loss():
    decisions.record(_doc(1, ts=1001.0))
    decisions.record(_doc(2, ts=1003.0))
    decisions.record(_doc(3, ts=1002.0))
    got = decisions.list_decisions()
    assert [x["decision_id"] for x in got] == ["dec_t37_2", "dec_t37_3", "dec_t37_1"]
    decisions._DECISIONS.clear()
    again = decisions.list_decisions()
    assert [x["decision_id"] for x in again] == ["dec_t37_2", "dec_t37_3", "dec_t37_1"]
    api = c.get("/v1/eval/decisions").json()["decisions"]
    assert [x["decision_id"] for x in api] == ["dec_t37_2", "dec_t37_3", "dec_t37_1"]


def test_list_capped_at_50():
    base = time.time()
    for i in range(60):
        decisions.record(_doc(i, ts=base + i))
    got = decisions.list_decisions()
    assert len(got) == 50
    assert got[0]["decision_id"] == "dec_t37_59"
    assert len(decisions.list_decisions(limit=200)) == 50
    assert decisions.list_decisions(limit=2)[0]["decision_id"] == "dec_t37_59"


def test_clear_removes_only_decisions():
    main._evidence["ev_t37_keep"] = {"id": "ev_t37_keep", "kind": "other", "ts": 1.0}
    try:
        decisions.record(_doc(9))
        assert len(decisions.list_decisions()) == 1
        decisions.clear()
        assert decisions.list_decisions() == []
        assert c.get("/v1/eval/decisions").json()["decisions"] == []
        assert main._evidence.get("ev_t37_keep")["kind"] == "other"
    finally:
        try:
            del main._evidence["ev_t37_keep"]
        except KeyError:
            pass
