"""Sealed scores require consistent execution evidence, never counts alone."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evoforge import runner, sealed_eval


@pytest.mark.parametrize("changes", [
    {"exit_code": 1}, {"exit_code": None}, {"exit_code": False},
    {"report_integrity": False}, {"report_integrity": "true"},
    {"n": True, "pass": True}, {"n": 1.0, "pass": 1.0},
    {"n": 0, "pass": 0}, {"pass": 0}, {"n": 2, "pass": 1},
])
def test_inconsistent_remote_counts_never_earn_credit(monkeypatch, changes):
    section = {"n": 1, "pass": 1, "exit_code": 0, "timed_out": False,
               "report_integrity": True, **changes}
    monkeypatch.setattr(sealed_eval._runner_client, "run_via_runner",
                        lambda *a: {"heldout": section})
    assert sealed_eval._run_heldout_remote("repo", "a" * 40, "", [{"code": "x"}], 10) == 0


@pytest.mark.parametrize("flag", [True, None])
def test_consistent_remote_result_and_legacy_flag_compatibility(monkeypatch, flag):
    section = {"n": 1, "pass": 1, "exit_code": 0, "timed_out": False}
    if flag is not None:
        section["report_integrity"] = flag
    monkeypatch.setattr(sealed_eval._runner_client, "run_via_runner",
                        lambda *a: {"heldout": section})
    assert sealed_eval._run_heldout_remote("repo", "a" * 40, "", [{"code": "x"}], 10) == 1


@pytest.mark.parametrize("detail", [False, True])
def test_local_inconsistent_report_is_never_success(monkeypatch, tmp_path, detail):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(runner, "_run_suite", lambda *a, **kw: {
        "n": 1, "pass": 1, "exit_code": 0, "timed_out": False, "report_integrity": False})
    held = [{"code": "def test_a():\n assert True\n"}]
    if detail:
        score, failures = sealed_eval._run_heldout_local_detail(str(repo), held, 30, str(tmp_path))
        assert score == 0 and failures[0]["verification"] == "INCONCLUSIVE"
    else:
        assert sealed_eval._run_heldout_local(str(repo), held, 30, str(tmp_path)) == 0


@pytest.mark.parametrize("passes", [True, False])
def test_real_local_subprocess_scores_agree_with_assertions(tmp_path, passes):
    repo = tmp_path / "repo"
    repo.mkdir()
    held = [{"code": "import pytest\n@pytest.mark.parametrize('x', [1, 2])\ndef test_a(x):\n assert x > " + ("0" if passes else "3") + "\n"}]
    score, failures = sealed_eval._run_heldout_local_detail(str(repo), held, 30, str(tmp_path))
    assert score == float(passes)
    assert bool(failures) is not passes
    assert all(f.get("verification") != "INCONCLUSIVE" for f in failures)


def test_actual_local_report_includes_verified_execution_channels(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    suite = [{"code": "def test_a():\n assert 1 + 1 == 2\n"}]
    folder = runner._write_suite(str(repo), "visible", "test_visible", suite)
    result = runner._run_suite(str(repo), folder, str(tmp_path / "report.xml"), suite, 30)
    assert result["report_integrity"] is True


def test_inconclusive_diagnostic_is_a_valid_score_outcome():
    assert "verification_inconclusive" in sealed_eval.SCORE_OUTCOMES
    assert sealed_eval._failed_run_outcome([{"verification": "INCONCLUSIVE"}]) == "verification_inconclusive"
    assert sealed_eval._failed_run_outcome([{"test": "test_a", "message": "assertion failed"}]) == "heldout_failed"


@pytest.mark.parametrize("pipeline", [False, True])
def test_evaluation_keeps_unconfirmed_task_unsolved_and_settles_usage(monkeypatch, pipeline):
    from evoforge import broker_meta, ledger

    task = sealed_eval.load_suites("v1")[0]["tasks"][0]
    family = "verification_test"
    monkeypatch.setattr(sealed_eval, "load_suites", lambda version: [{"family": family, "tasks": [task]}])
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset()
    ledger.configure({"default": 100000})
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **kw: {
        "diff": task["reference_fix"], "tests": [], "stub": False,
        "model": sealed_eval.BASELINE_MODEL,
        "usage": {"prompt_tokens": 1000000, "completion_tokens": 0}})
    monkeypatch.setattr(runner, "_run_suite", lambda *a, **kw: {
        "n": len(task["heldout"]), "pass": len(task["heldout"]), "exit_code": 0,
        "timed_out": False, "report_integrity": False})
    try:
        kwargs = {"max_attempts": 1} if pipeline else {}
        result = (sealed_eval.run_pipeline if pipeline else sealed_eval.run_baseline)(
            "v1", sealed_eval.BASELINE_MODEL, family=family, **kwargs)
        row = result["scores"][0]
        assert row["score"] == 0 and row["outcome"] == "verification_inconclusive"
        assert ledger.snapshot()["reserved_cents"] == 0
        assert ledger.snapshot()["spent_cents"] > 0
    finally:
        ledger.reset()
