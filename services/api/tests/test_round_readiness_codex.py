"""v3.8: incomplete rendering and inconsistent reports cannot be READY."""
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evoforge import evolution_rounds as rounds, runner, sealed_eval as sealed


def _preview(html="<html><body>new round</body></html>"):
    return {"preview_html": html, "preview_sha": "sha256:" + hashlib.sha256(html.encode()).hexdigest()}


@pytest.mark.parametrize("preview, ready", [
    (_preview(), True), (_preview(""), False), (_preview("  "), False),
    ({**_preview(), "preview_error": "render failed"}, False),
    ({**_preview(), "preview_sha": "sha256:" + "a" * 64}, False),
    ({"preview_html": "<html/>"}, False),
])
def test_preview_requires_nonempty_render_with_matching_digest(preview, ready):
    assert rounds._preview_ready(preview) is ready


@pytest.mark.parametrize("lane", ["single", "evoforge"])
@pytest.mark.parametrize("render_ok", [False, True])
def test_snapshot_cannot_be_ready_just_because_tests_pass(monkeypatch, lane, render_ok):
    old = {"app.py": "old"}
    new = {"app.py": "new"}
    out = {"diff": "candidate diff"}
    monkeypatch.setattr(sealed, "_call_builder_task", lambda *a: ("r", out, 1, False))
    monkeypatch.setattr(sealed, "_call_pipeline_attempt", lambda *a: ("r", out, 1, False))
    monkeypatch.setattr(rounds, "_apply_diff_to_files", lambda *a, **kw: (new, True))
    monkeypatch.setattr(rounds, "_score_files_counted", lambda *a: (1, 1, []))
    preview = _preview() if render_ok else {**_preview(""), "preview_error": "render failed"}
    monkeypatch.setattr(rounds, "_score_and_preview", lambda *a: (1, 1, [], 1, 1, preview, None))
    app_round = {"index": 1, "goal": "x", "heldout": [{"code": "x"}]}
    if lane == "single":
        files, snap = rounds._run_single_round(app_round, app_round["heldout"], old, 10)
    else:
        files, snap = rounds._run_evoforge_round(app_round, app_round["heldout"], old, "heldout", 10)
    assert files == new
    assert snap["status"] == ("READY" if render_ok else "UNVERIFIED")
    assert snap["verified"] is render_ok


@pytest.mark.parametrize("lane", ["single", "evoforge"])
def test_failed_round_never_relabels_previous_preview_as_current(monkeypatch, lane):
    old = {"app.py": "previous"}
    monkeypatch.setattr(sealed, "_call_builder_task", lambda *a: ("r", {"diff": ""}, 1, False))
    monkeypatch.setattr(sealed, "_call_pipeline_attempt", lambda *a: ("r", {"diff": ""}, 1, False))
    monkeypatch.setattr(sealed, "PIPELINE_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(rounds, "_score_and_preview", lambda *a: (1, 1, [], 1, 1, _preview("<p>previous round</p>"), None))
    app_round = {"index": 2, "goal": "x", "heldout": [{"code": "x"}]}
    if lane == "single":
        files, snap = rounds._run_single_round(app_round, app_round["heldout"], old, 10)
    else:
        files, snap = rounds._run_evoforge_round(app_round, app_round["heldout"], old, "heldout", 10)
    assert files == old and snap["status"] == "FAILED"
    assert snap["preview_html"] == "" and snap["preview_error"]
    assert snap["verified"] is False


@pytest.mark.parametrize("changes", [{"report_integrity": False}, {"n": True, "pass": True}, {"exit_code": 1}])
def test_round_score_rejects_inconsistent_execution(monkeypatch, changes):
    monkeypatch.setattr(sealed, "_make_task_source_repo", lambda *a: ("unused", "a" * 40, []))
    monkeypatch.setattr(sealed, "_build_clean_sandbox", lambda *a: [])
    monkeypatch.setattr(runner, "_run_suite", lambda *a, **kw: {
        "n": 1, "pass": 1, "exit_code": 0, "timed_out": False, "report_integrity": True, **changes})
    passed, n, failures = rounds._score_files_counted({"app.py": "x"}, [{"code": "x"}], 10, "round1")
    assert (passed, n) == (0, 1)
    assert failures[0]["verification"] == "INCONCLUSIVE"


def test_round_report_uncertainty_reaches_snapshot_orchestration(monkeypatch):
    monkeypatch.setattr(rounds, "_score_files_counted", lambda *a: (
        0, 1, [{"verification": "INCONCLUSIVE", "test": "held-out", "message": "unconfirmed"}]))
    monkeypatch.setattr(rounds, "_preview_snapshot", lambda *a: _preview())
    result = rounds._score_and_preview({"app.py": "x"}, [{"code": "x"}], [{"code": "x"}], 10, "r1")
    assert result[-1] == "execution verification inconclusive"


def test_round_screen_runs_before_any_patch_application():
    diff = "--- a/app.py\n+++ b/app.py\n@@ -0,0 +1 @@\n+import atexit\n"
    assert rounds._apply_diff_to_files({}, diff, True) == (None, False)
