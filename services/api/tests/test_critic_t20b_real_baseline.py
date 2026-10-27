"""Critic acceptance (sealed during build, promoted after) — T20b X_SINGLE must measure the Builder: no fix -> 0, reference fix -> 1."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, commands, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    ledger.reset()
    ledger.configure({"default": 500000})
    commands.reset()


def _tasks():
    return [t for s in sealed_eval.load_suites() for t in s["tasks"]]


def test_every_task_has_starting_code_and_a_server_side_reference_fix():
    tasks = _tasks()
    assert len(tasks) >= 12
    for t in tasks:
        assert isinstance(t.get("files"), dict) and t["files"], t["id"]
        assert isinstance(t.get("reference_fix"), str) and "+++ " in t["reference_fix"], t["id"]
        assert len(t["heldout"]) >= 3


def test_heldout_fails_without_fix_and_passes_with_reference_fix():
    for t in _tasks():
        r = sealed_eval.check_task(t)
        assert r["fails_without_fix"] is True, (t["id"], "held-out passes with no fix: test is not measuring anything")
        assert r["passes_with_fix"] is True, (t["id"], "reference fix does not satisfy its own held-out suite")


def test_validation_runs_locally_even_when_runner_configured(monkeypatch):
    """Suite validation must not depend on the runner service: the validation
    source repo is ephemeral-local, so a configured runner URL must be ignored."""
    from evoforge import runner_client as _rc

    monkeypatch.setattr(_rc, "runner_url", lambda: "https://runner.invalid")
    monkeypatch.setattr(_rc, "run_via_runner", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call runner")))
    t = _tasks()[0]
    r = sealed_eval.check_task(t)
    assert r["fails_without_fix"] is True and r["passes_with_fix"] is True


def test_no_fix_scores_zero(monkeypatch):
    calls = []

    def builder(goal, sha, file_context=None, **k):
        calls.append(goal)
        return {"diff": "", "tests": [], "rationale": "nothing", "stub": False, "model": "m", "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", builder)
    r = c.post("/v1/eval/baseline", json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code == 201, r.text
    x = r.json()["X_SINGLE"]
    assert x["n"] == len(_tasks()) and x["pass_rate"] == 0.0
    assert len(calls) == x["n"]  # one Builder attempt per task (X_SINGLE)


def test_reference_fix_scores_one_and_builder_sees_task_files(monkeypatch):
    by_goal = {t["goal"]: t for t in _tasks()}
    seen = []

    def builder(goal, sha, file_context=None, **k):
        t = next(v for g, v in by_goal.items() if g in goal or goal in g)
        seen.append({e["path"] for e in (file_context or [])} >= set(t["files"]))
        return {"diff": t["reference_fix"], "tests": [], "rationale": "ref", "stub": False, "model": "m",
                "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", builder)
    before = ledger.snapshot()["spent_cents"]
    r = c.post("/v1/eval/baseline", json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code == 201, r.text
    x = r.json()["X_SINGLE"]
    assert x["pass_rate"] == 1.0 and x["n"] == len(_tasks())
    assert seen and all(seen)
    assert x["cost_cents"] == ledger.snapshot()["spent_cents"] - before > 0
    body = json.dumps(r.json())
    assert "def test_" not in body and "+++ " not in body  # neither sealed tests nor reference fixes leave the server


def test_reference_fix_never_exposed_over_http():
    r = c.get("/v1/eval/suites")
    assert r.status_code == 200 and "reference_fix" not in r.text and "+++ " not in r.text


def test_baseline_runs_locally_even_when_runner_configured(monkeypatch):
    """Sealed tasks live in ephemeral local repos: a configured runner service
    must not break the baseline (live 502: RunnerBadRequest)."""
    from evoforge import runner_client as _rc

    monkeypatch.setenv("EVO_RUNNER_URL", "https://runner.invalid")
    monkeypatch.setattr(_rc, "run_via_runner", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call runner")))

    def builder(goal, sha, file_context=None, **k):
        return {"diff": "", "tests": [], "rationale": "nothing", "stub": False, "model": "m", "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", builder)
    r = c.post("/v1/eval/baseline", json={"suite_version": "v0", "model": "muse-spark-1.3",
                                          "family": "simple_sequential"})
    assert r.status_code == 201, r.text
    assert r.json()["X_SINGLE"]["n"] == 2
