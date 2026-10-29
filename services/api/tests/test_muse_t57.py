"""T57 retire stale Critic tests in evolution runs (local unit checks)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import evolution_rounds as ev  # noqa: E402
from evoforge import sealed_eval as se  # noqa: E402


def _stub(monkeypatch, critic_new_code, score_behavior):
    monkeypatch.setattr(
        se, "_critic_goal_for_task", lambda task, fc: task.get("goal", ""))
    monkeypatch.setattr(
        se, "_call_critic_suite",
        lambda goal: ("rsv", {"sealed_tests": [{"code": critic_new_code}]}, 10, False))
    monkeypatch.setattr(
        se, "_critic_suite_from_output",
        lambda out: [{"code": t["code"]} for t in out.get("sealed_tests", [])])
    monkeypatch.setattr(se, "_is_empty_diff",
                        lambda d: not (isinstance(d, str) and d.strip()))
    monkeypatch.setattr(
        ev, "_apply_diff_to_files",
        lambda files, diff, recount: ({**files, "board.py": diff}, True))
    counter = {"n": 0}
    goals = []

    def _attempt(goal, base, fc):
        counter["n"] += 1
        goals.append(goal)
        return ("rsv", {"diff": "diff-%d" % counter["n"]}, 10, False)

    monkeypatch.setattr(se, "_call_pipeline_attempt", _attempt)
    monkeypatch.setattr(ev, "_score_files_counted", score_behavior)
    monkeypatch.setattr(
        ev, "_score_and_preview",
        lambda files, cumulative, round_heldout, timeout_s, tag: (
            len(cumulative), len(cumulative), [], len(round_heldout or []),
            len(round_heldout or []),
            {"preview_html": "", "preview_sha": "sha256:" + "0" * 64}, None))
    return counter, goals


def test_stale_earlier_test_retired_after_two_identical_failures(monkeypatch):
    def _score(files, suite, timeout_s, tag):
        return (1, 2, [{"test": "mod::test_critic_old",
                        "message": "AssertionError"}])
    _stub(monkeypatch, "def test_critic_new():\n    assert 1\n", _score)
    hist = [{"code": "def test_critic_old():\n    assert 1\n"}]
    _, snap = ev._run_evoforge_round(
        {"index": 2, "goal": "Round 2 goal", "heldout": []}, [], {"board.py": "b"},
        "critic", 10, hist)
    assert snap["critic_tests"] == 2
    assert snap["critic_retired"] == 1
    assert snap["attempts"] == 2
    assert all("test_critic_old" not in (e.get("code", "")) for e in hist)
    assert len(hist) == 1
    msgs = [e["message"] for e in snap["events"] if e["role"] == "critic"]
    assert any("retired 1 stale Critic tests" in m for m in msgs)


def test_regression_still_retried(monkeypatch):
    calls = {"n": 0}

    def _score(files, suite, timeout_s, tag):
        calls["n"] += 1
        if calls["n"] == 1:
            return (1, 2, [{"test": "mod::test_critic_old",
                            "message": "AssertionError"}])
        return (2, 2, [])
    _stub(monkeypatch, "def test_critic_new():\n    assert 1\n", _score)
    hist = [{"code": "def test_critic_old():\n    assert 1\n"}]
    _, snap = ev._run_evoforge_round(
        {"index": 2, "goal": "Round 2 goal", "heldout": []}, [], {"board.py": "b"},
        "critic", 10, hist)
    assert snap["critic_retired"] == 0
    assert snap["attempts"] == 2
    assert len(hist) == 2
