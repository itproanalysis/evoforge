"""Critic — W13: sealed v1 is selectable end to end; v0 stays the default and unchanged."""
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
from evoforge import broker_meta, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    ledger.reset()
    ledger.configure({"default": 500000})
    from evoforge import performance
    performance.clear()


def test_v1_keeps_v0_tests_files_and_fixes_and_changes_only_goals():
    v0 = {t["id"][4:]: t for s in sealed_eval.load_suites("v0") for t in s["tasks"]}
    v1 = {t["id"][4:]: t for s in sealed_eval.load_suites("v1") for t in s["tasks"]}
    assert set(v0) == set(v1) and len(v1) == 12
    for k in v0:
        for field in ("files", "reference_fix", "heldout"):
            assert v0[k][field] == v1[k][field], (k, field)
    assert sum(v0[k]["goal"] != v1[k]["goal"] for k in v0) >= 11


def test_default_is_v0_and_unknown_versions_are_refused():
    assert sealed_eval.sealed_dir().endswith("sealed_v0")
    with pytest.raises(ValueError):
        sealed_eval.sealed_dir("v9")
    assert c.post("/v1/eval/baseline", json={"suite_version": "v9"}).status_code == 422


def test_suites_endpoint_lists_versions_and_serves_v1_redacted():
    body = c.get("/v1/eval/suites?suite_version=v1").json()
    assert body["suite_version"] == "v1" and body["suite_versions"] == ["v0", "v1", "v2", "v3", "v4"]
    blob = json.dumps(body)
    for s in sealed_eval.load_suites("v1"):
        for t in s["tasks"]:
            for h in t["heldout"]:
                assert h["code"] not in blob
    assert c.get("/v1/eval/suites").json()["suite_version"] == "v0"


def test_v1_baseline_records_a_v1_measurement(monkeypatch):
    tasks = {t["goal"]: t for s in sealed_eval.load_suites("v1") for t in s["tasks"]}

    def builder(goal, sha, file_context=None, **k):
        t = tasks.get(goal)
        return {"diff": t["reference_fix"] if t else "", "tests": [], "rationale": "x", "stub": False,
                "model": "m", "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", builder)
    r = c.post("/v1/eval/baseline", json={"suite_version": "v1", "family": "simple_sequential"})
    assert r.status_code == 201, r.text
    assert r.json()["suite_version"] == "v1"
    base = c.get("/v1/performance").json()["baseline"]
    assert base["status"] == "measured" and base["suite_version"] == "v1" and base["passed"] == base["n"] == 2
