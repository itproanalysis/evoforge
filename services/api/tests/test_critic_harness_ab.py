"""Critic — the service can A/B its own harness on one suite: /1 strict hunk counts vs /2 recount (T26)."""
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


def _overcount(diff: str) -> str:
    """Make every hunk header claim one more line on each side (the off-by-one real Builders produce)."""
    import re
    return re.sub(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@",
                  lambda m: f"@@ -{m.group(1)},{int(m.group(2)) + 1} +{m.group(3)},{int(m.group(4)) + 1} @@",
                  diff, flags=re.M)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    ledger.reset(); ledger.configure({"default": 500000})
    from evoforge import performance
    performance.clear()
    tasks = {t["goal"]: t for s in sealed_eval.load_suites("v2") for t in s["tasks"]}
    monkeypatch.setattr(broker_meta, "call_builder", lambda goal, sha, file_context=None, **k: {
        "diff": _overcount(tasks[goal]["reference_fix"]) if goal in tasks else "", "tests": [], "rationale": "x",
        "stub": False, "model": "m", "provider_calls": []})


def _run(harness):
    r = c.post("/v1/eval/baseline", json={"suite_version": "v2", "family": "simple_sequential", "harness_version": harness})
    assert r.status_code == 201, r.text
    return r.json()["measurement"]


def test_strict_harness_rejects_miscounted_diffs_and_recount_harness_applies_them():
    strict = _run("api-sealed-eval/1")
    recount = _run("api-sealed-eval/2")
    assert strict["harness_version"] == "api-sealed-eval/1" and strict["passed"] == 0
    assert recount["harness_version"] == "api-sealed-eval/2" and recount["passed"] == recount["n"] == 6
    hist = c.get("/v1/performance").json()["history"]
    assert [h["harness_version"] for h in hist] == ["api-sealed-eval/1", "api-sealed-eval/2"]


def test_default_harness_is_the_current_one():
    m = _run(None)
    assert m["harness_version"] == sealed_eval.HARNESS_VERSION


def test_unknown_harness_is_422():
    r = c.post("/v1/eval/baseline", json={"suite_version": "v2", "harness_version": "api-sealed-eval/9"})
    assert r.status_code == 422


def test_v2_has_36_tasks_including_all_of_v1():
    v2 = [t for s in sealed_eval.load_suites("v2") for t in s["tasks"]]
    assert len(v2) == 36
    v1_ids = {t["id"][4:] for s in sealed_eval.load_suites("v1") for t in s["tasks"]}
    assert v1_ids <= {t["id"][4:] for t in v2}
