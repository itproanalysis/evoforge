"""Critic — the pipeline scores sealed tasks locally even when EVO_RUNNER_URL is set (production RunnerBadRequest)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


def test_pipeline_with_runner_configured_never_sends_ephemeral_tasks_to_the_runner(monkeypatch):
    ledger.reset(); ledger.configure({"default": 500000})
    from evoforge import performance
    performance.clear()
    monkeypatch.setenv("EVO_RUNNER_URL", "https://runner.invalid")
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    monkeypatch.setattr(sealed_eval, "_run_heldout_remote",
                        lambda *a, **k: pytest.fail("pipeline must not use the remote runner for sealed tasks"))
    tasks = {t["goal"]: t for s in sealed_eval.load_suites("v1") for t in s["tasks"]}
    monkeypatch.setattr(broker_meta, "call_builder", lambda goal, sha, file_context=None, **k: {
        "diff": next((t["reference_fix"] for g, t in tasks.items() if g in goal), ""), "tests": [], "rationale": "x",
        "stub": False, "model": "m", "provider_calls": []})
    r = c.post("/v1/eval/pipeline", json={"suite_version": "v1", "family": "simple_sequential"})
    assert r.status_code == 201, r.text
    assert c.get("/v1/performance").json()["pipeline"]["passed"] == 2
