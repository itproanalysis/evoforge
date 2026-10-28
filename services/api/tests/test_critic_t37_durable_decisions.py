"""Critic acceptance (sealed during build, promoted after) — T37: harness adoption decisions are stored in the evidence store (memory or PostgreSQL), so they
survive a redeploy like measurements and certificates do."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import decisions  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


def _decision(i, verdict="improved"):
    return {"decision_id": f"dec_{i:04d}", "created_at": 1000.0 + i, "suite_version": "v2", "kind": "X_SINGLE",
            "model": "muse-spark-1.3", "family": None, "champion": "api-sealed-eval/1",
            "challenger": "api-sealed-eval/2", "verdict": verdict,
            "decision": "adopt" if verdict == "improved" else "keep", "reason": "r",
            "champion_measurement": {"passed": 21, "n": 36, "wilson95": [0.42, 0.73]},
            "challenger_measurement": {"passed": 35, "n": 36, "wilson95": [0.86, 0.99]}}


def test_decisions_are_written_to_the_evidence_store():
    decisions.record(_decision(1))
    stored = [v for k, v in main._evidence.items() if isinstance(v, dict) and v.get("kind") == "harness_decision"]
    assert any(v.get("decision", {}).get("decision_id") == "dec_0001" or v.get("decision_id") == "dec_0001" for v in stored), stored


def test_decisions_survive_a_process_restart():
    decisions.record(_decision(2))
    inmem = getattr(decisions, "_DECISIONS", None)
    if isinstance(inmem, list):
        inmem.clear()  # what a redeploy does to process memory
    ids = [d["decision_id"] for d in c.get("/v1/eval/decisions").json()["decisions"]]
    assert "dec_0002" in ids


def test_list_is_newest_first_and_capped():
    for i in range(10, 70):
        decisions.record(_decision(i, "no_clear_difference" if i % 2 else "improved"))
    ds = c.get("/v1/eval/decisions").json()["decisions"]
    assert len(ds) <= 50
    assert [d["created_at"] for d in ds] == sorted((d["created_at"] for d in ds), reverse=True)
