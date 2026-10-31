"""Prompt-arena file names, the judge instruction, Critic counts and reflective retries.

Live probes on 2026-10-31 showed four defects: a request naming csvlite.py left the judge with 0 tests
(job_34f00ed1825d); the judge was told to test only app.render(); progress read "Critic 20/3" (functions
over files); and the EvoForge lane repeated the same Critic failure three times (job_cd3d388389e1).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

import main  # noqa: E402,F401
from evoforge import arena as arena_mod  # noqa: E402
from evoforge import arena_prompt, broker_meta, commands, eval_jobs, ledger, sealed_eval  # noqa: E402

TASK_ID = "SV2-SS-01"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset()
    ledger.configure({"default": 500000})
    commands.reset()
    eval_jobs.clear()
    arena_mod.clear()
    yield
    arena_mod.clear()
    ledger.reset()
    ledger.configure({"default": 500000})


def _task() -> dict:
    return arena_mod.find_task("v2", TASK_ID)


def _usage():
    return {"prompt_tokens": 1000, "completion_tokens": 200}


def _critic(monkeypatch, body: str):
    mod = sorted(_task()["files"])[0][:-3]

    def fake(goal, diff="", ci="", **k):
        return {"sealed_tests": [{"code": f"import {mod}\n\n{body}"}],
                "review": {"result": "PASS"}, "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": {"prompt_tokens": 100, "completion_tokens": 50}}

    monkeypatch.setattr(broker_meta, "call_critic", fake)


def _builder(monkeypatch, goals: list, empty_first: int = 0):
    fix = _task()["reference_fix"]

    def fake(goal, sha, file_context=None, **k):
        goals.append(goal)
        diff = "" if len(goals) <= empty_first else fix
        return {"diff": diff, "tests": [], "rationale": "x", "stub": False,
                "model": "muse-spark-1.3", "provider_calls": [], "usage": _usage()}

    monkeypatch.setattr(broker_meta, "call_builder", fake)


def _no_heldout_in(task, blob):
    for name in sealed_eval._heldout_test_names(task["heldout"]):
        assert name not in blob, name
    for h in task["heldout"]:
        assert h["code"] not in blob


def test_named_files_point_at_app_py():
    text, renamed = arena_prompt.normalize_modules(
        "In csvlite.py provide parse(text); from csvlite import parse. Do not import csv.")
    assert renamed == ["csvlite"]
    assert "In app.py provide parse" in text and "from app import parse" in text
    assert "Do not import csv." in text
    assert "csvlite.py means app.py" in text
    for prompt in ("Build app.py with add()", "see docs/x.py and ./run.py", "plain request"):
        assert arena_prompt.normalize_modules(prompt) == (prompt, [])
    judge = arena_prompt.build_judge_goal("In slots.py provide free_slots()")
    task = arena_prompt.build_task_goal("In slots.py provide free_slots()")
    for goal in (judge, task):
        assert "In app.py provide free_slots()" in goal
    follow = arena_prompt.build_followup_judge_goal(["In a.py provide f()"], "In b.py provide g()")
    assert "In app.py provide f()" in follow and "In app.py provide g()" in follow
    m = arena_prompt.build_manifest("In split.py provide allocate()", "critic", "tolerant")
    assert m["modules_renamed"] == ["split"]
    assert "modules_renamed" not in arena_prompt.build_manifest("say hello", "critic", "tolerant")


def test_judge_tests_every_named_function_not_only_render():
    instr = arena_prompt.JUDGE_INSTRUCTION
    assert "every function the request names" in instr
    assert "render(state)" in instr and "dict" in instr


def test_critic_count_uses_test_functions_on_both_sides(monkeypatch):
    _critic(monkeypatch, "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 1\n")
    _builder(monkeypatch, [])
    lane = arena_mod._run_evoforge_lane(_task(), "muse-spark-1.3", 60, feedback="critic")
    msgs = [e["message"] for e in lane["events"]]
    assert any("Critic 2/2 passed" in m for m in msgs), msgs
    assert not any("Critic 2/1 passed" in m for m in msgs), msgs


def test_repeated_critic_failure_changes_approach(monkeypatch):
    task = _task()
    _critic(monkeypatch, "def test_spec_needs_more():\n    assert 1 == 2, 'needs more'\n")
    goals: list = []
    _builder(monkeypatch, goals)
    lane = arena_mod._run_evoforge_lane(task, "muse-spark-1.3", 60, feedback="critic")
    assert lane["attempts"] == 3, lane
    assert sealed_eval.REFLECT_NOTE not in goals[0]
    assert sealed_eval.REFLECT_NOTE in goals[1] and sealed_eval.REPEAT_NOTE not in goals[1]
    assert sealed_eval.REFLECT_NOTE in goals[2] and sealed_eval.REPEAT_NOTE in goals[2]
    msgs = [e["message"] for e in lane["events"]]
    assert any("changing approach" in m for m in msgs), msgs
    _no_heldout_in(task, json.dumps(goals))


def test_second_empty_diff_asks_for_the_smallest_complete_patch(monkeypatch):
    task = _task()
    _critic(monkeypatch, "def test_ok():\n    assert 1\n")
    goals: list = []
    _builder(monkeypatch, goals, empty_first=2)
    lane = arena_mod._run_evoforge_lane(task, "muse-spark-1.3", 60, feedback="critic")
    assert lane["outcome"] == "passed", lane
    assert lane["attempts"] == 3
    assert "empty diff" in goals[1] and sealed_eval.EMPTY_REPEAT_NOTE not in goals[1]
    assert sealed_eval.EMPTY_REPEAT_NOTE in goals[2]
    _no_heldout_in(task, json.dumps(goals))


def test_reflective_feedback_helpers():
    fb = sealed_eval._critic_feedback("goal", [{"test": "t", "message": "m"}], 1, 0)
    assert sealed_eval._reflective_feedback(fb, False) == fb + "\n\n" + sealed_eval.REFLECT_NOTE
    assert sealed_eval.REPEAT_NOTE in sealed_eval._reflective_feedback(fb, True)
    a = sealed_eval._failure_signature([{"test": "t", "message": "m"}, {"test": "u", "message": "n"}])
    b = sealed_eval._failure_signature([{"test": "u", "message": "n"}, {"test": "t", "message": "m"}])
    assert a == b != sealed_eval._failure_signature([{"test": "t", "message": "other"}])
