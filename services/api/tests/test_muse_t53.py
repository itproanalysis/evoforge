"""T53 cumulative Critic suite in evolution runs (local unit checks)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import evolution_rounds as ev  # noqa: E402
from evoforge import sealed_eval as se  # noqa: E402


def _stub_common(monkeypatch, critic_by_goal, score_behavior=None, feedback_log=None):
    monkeypatch.setattr(
        se, "_critic_goal_for_task", lambda task, fc: task.get("goal", ""))
    def _critic_suite(goal):
        code = critic_by_goal.get(goal, [])
        return ("rsv", {"sealed_tests": [{"code": c} for c in code]}, 10, False)
    monkeypatch.setattr(se, "_call_critic_suite", _critic_suite)
    monkeypatch.setattr(
        se, "_critic_suite_from_output",
        lambda out, *_a, **_k: [{"code": t["code"]} for t in out.get("sealed_tests", [])])
    monkeypatch.setattr(se, "_is_empty_diff",
                        lambda d: not (isinstance(d, str) and d.strip()))
    monkeypatch.setattr(
        ev, "_apply_diff_to_files",
        lambda files, diff, recount: ({**files, "board.py": diff}, True))
    counter = {"n": 0}
    def _attempt(goal, base, fc):
        counter["n"] += 1
        return ("rsv", {"diff": "diff-%d" % counter["n"]}, 10, False)
    monkeypatch.setattr(se, "_call_pipeline_attempt", _attempt)
    seen = {"suites": []}
    def _score(files, suite, timeout_s, tag):
        seen["suites"].append(list(suite))
        if score_behavior is not None:
            return score_behavior(files, suite, tag, len(seen["suites"]))
        return (len(suite), len(suite), [])
    monkeypatch.setattr(ev, "_score_files_counted", _score)
    monkeypatch.setattr(
        ev, "_score_and_preview",
        lambda files, cumulative, round_heldout, timeout_s, tag: (
            len(cumulative), len(cumulative), [], len(round_heldout or []),
            len(round_heldout or []),
            {"preview_html": "", "preview_sha": "sha256:" + "0" * 64}, None))
    if feedback_log is not None:
        orig = se._critic_feedback
        def _spy(goal, failures, n, passed):
            feedback_log.append((list(failures), int(n), int(passed)))
            return orig(goal, failures, n, passed)
        monkeypatch.setattr(se, "_critic_feedback", _spy)
    return seen


def test_accumulated_suite_grows_and_is_used(monkeypatch):
    seen = _stub_common(monkeypatch, {
        "Round 1 goal": ["def test_critic_r1():\n    assert 1\n"],
        "Round 2 goal": ["def test_critic_r2():\n    assert 1\n"],
    })
    hist = []
    files = {"board.py": "base"}
    _, snap1 = ev._run_evoforge_round(
        {"index": 1, "goal": "Round 1 goal", "heldout": []}, [], files,
        "critic", 10, hist)
    assert snap1["critic_tests"] == 1
    msgs1 = [e["message"] for e in snap1["events"] if e["role"] == "critic"]
    assert any(re.fullmatch(r"Critic suite: 1 tests \(1 new\)", m) for m in msgs1)
    seen["suites"].clear()
    new_files, snap2 = ev._run_evoforge_round(
        {"index": 2, "goal": "Round 2 goal", "heldout": []}, [], files,
        "critic", 10, hist)
    assert snap2["critic_tests"] == 2
    msgs2 = [e["message"] for e in snap2["events"] if e["role"] == "critic"]
    assert any(re.fullmatch(r"Critic suite: 2 tests \(1 new\)", m) for m in msgs2)
    assert seen["suites"], "critic suite must be scored on applied attempts"
    assert len(seen["suites"][0]) == 2


def test_retry_feedback_lists_earlier_round_failures(monkeypatch):
    feedback_log = []
    def _behavior(files, suite, tag, call_no):
        if call_no == 1:
            return (0, 2, [{"test": "mod::test_critic_r1",
                            "message": "AssertionError"}])
        return (2, 2, [])
    _stub_common(monkeypatch, {
        "Round 2 goal": ["def test_critic_r2():\n    assert 1\n"],
    }, score_behavior=_behavior, feedback_log=feedback_log)
    hist = [{"code": "def test_critic_r1():\n    assert 1\n"}]
    _, snap = ev._run_evoforge_round(
        {"index": 2, "goal": "Round 2 goal", "heldout": []}, [], {"board.py": "b"},
        "critic", 10, hist)
    assert snap["critic_tests"] == 2
    assert feedback_log, "a failing critic attempt must feed back"
    failures, n, _passed = feedback_log[0]
    assert n == 2
    assert any("test_critic_r1" in f["test"] for f in failures)


def test_heldout_never_enters_feedback_and_single_has_no_critic_tests(monkeypatch):
    monkeypatch.setattr(se, "_is_empty_diff",
                        lambda d: not (isinstance(d, str) and d.strip()))
    monkeypatch.setattr(
        ev, "_apply_diff_to_files",
        lambda files, diff, recount: ({**files, "board.py": diff}, True))
    monkeypatch.setattr(se, "_call_pipeline_attempt",
                        lambda goal, base, fc: ("rsv", {"diff": "d"}, 10, False))
    monkeypatch.setattr(ev, "_score_files_counted", lambda *a, **k: (1, 1, []))
    monkeypatch.setattr(
        ev, "_score_and_preview",
        lambda files, cumulative, round_heldout, timeout_s, tag: (
            len(cumulative), len(cumulative), [], 1, 1,
            {"preview_html": "", "preview_sha": "sha256:" + "0" * 64}, None))
    monkeypatch.setattr(se, "_call_builder_task",
                        lambda goal, base, fc: ("rsv", {"diff": "d"}, 10, False))
    _, single = ev._run_single_round(
        {"index": 1, "goal": "g", "heldout": [{"code": "x"}]}, [{"code": "x"}],
        {"board.py": "base"}, 10)
    assert single.get("critic_tests", 0) == 0
    assert all(e["role"] != "critic" for e in single["events"])
