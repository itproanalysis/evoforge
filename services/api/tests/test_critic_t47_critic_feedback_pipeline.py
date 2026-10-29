"""Sealed (Critic) — T47: a pipeline whose retry feedback comes only from the independent Critic's own tests; held-out
tests are used for the final score only (no oracle feedback)."""
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
FAMILY = "simple_sequential"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    from evoforge import performance
    performance.clear()


def _tasks():
    return [t for s in sealed_eval.load_suites("v2") if s["family"] == FAMILY for t in s["tasks"]]


def _critic_tests_for(task):
    # The Critic writes its own test from the goal, independent of the held-out suite: it imports the module and
    # asserts something the reference fix makes true (here: the first held-out-free check we can derive is "module
    # imports and the fixed behaviour differs from the original").
    mod = sorted(task["files"])[0][:-3]
    return [{"code": f"import {mod}\n\ndef test_critic_{mod}_imports():\n    assert {mod} is not None\n"}]


def _install(monkeypatch, builder_log, critic_log):
    tasks = {t["goal"]: t for t in _tasks()}

    def critic(goal, diff="", ci="", **k):
        critic_log.append({"goal": goal, "diff": diff, "ci": ci})
        t = next((tasks[g] for g in tasks if g in goal), None)
        return {"sealed_tests": _critic_tests_for(t) if t else [], "review": {"result": "PASS"}, "stub": False,
                "usage": {"prompt_tokens": 100, "completion_tokens": 50}}

    seen = {}

    def builder(goal, sha, file_context=None, **k):
        builder_log.append(goal)
        t = next((tasks[g] for g in tasks if g in goal), None)
        n = seen[t["id"]] = seen.get(t["id"], 0) + 1
        diff = t["reference_fix"] if n >= 2 else ""
        return {"diff": diff, "tests": [], "rationale": "x", "stub": False, "model": "m", "provider_calls": [],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100}}

    monkeypatch.setattr(broker_meta, "call_critic", critic)
    monkeypatch.setattr(broker_meta, "call_builder", builder)


def test_critic_feedback_never_carries_heldout_names_or_lines(monkeypatch):
    blog, clog = [], []
    _install(monkeypatch, blog, clog)
    r = c.post("/v1/eval/pipeline", json={"suite_version": "v2", "family": FAMILY, "feedback": "critic"})
    assert r.status_code == 201, r.text
    blob = json.dumps(blog) + json.dumps(clog)
    for t in _tasks():
        for h in t["heldout"]:
            name = h["code"].split("def ", 1)[1].split("(", 1)[0]
            assert name not in blob, f"held-out test name {name} reached the Builder or Critic"
            assert h["code"] not in blob
    assert clog, "the Critic must be called"


def test_heldout_decides_the_score_and_measurement_records_the_feedback_source(monkeypatch):
    _install(monkeypatch, [], [])
    r = c.post("/v1/eval/pipeline", json={"suite_version": "v2", "family": FAMILY, "feedback": "critic"})
    assert r.status_code == 201, r.text
    m = r.json()["measurement"]
    assert m["feedback_source"] == "critic"
    assert m["passed"] == m["n"] == len(_tasks())          # attempt 2 carries the reference fix
    assert m["attempts_total"] >= m["n"]
    assert m["cost_cents"] > 0                              # Builder and Critic usage both settled


def test_default_feedback_source_is_reported_honestly(monkeypatch):
    _install(monkeypatch, [], [])
    m = c.post("/v1/eval/pipeline", json={"suite_version": "v2", "family": FAMILY}).json()["measurement"]
    assert m["feedback_source"] == "heldout"


def test_bad_feedback_value_is_422():
    assert c.post("/v1/eval/pipeline", json={"suite_version": "v2", "feedback": "oracle"}).status_code == 422


def test_jobs_accept_the_feedback_option(monkeypatch):
    _install(monkeypatch, [], [])
    r = c.post("/v1/eval/jobs", json={"kind": "PIPELINE", "suite_version": "v2", "family": FAMILY, "feedback": "critic"})
    assert r.status_code == 202, r.text
