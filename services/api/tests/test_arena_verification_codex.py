"""Arena and eval results stay unconfirmed until execution evidence agrees."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evoforge import arena, broker_meta, ledger, runner, sealed_eval as sealed


@pytest.mark.parametrize("changes", [
    {"report_integrity": False}, {"n": True, "pass": True},
    {"n": 1.5, "pass": 1.5}, {"exit_code": 1},
    {"exit_code": None}, {"n": 0, "pass": 0},
])
def test_arena_does_not_convert_invalid_counts_to_success(monkeypatch, tmp_path, changes):
    result = {"n": 1, "pass": 1, "exit_code": 0, "timed_out": False,
              "report_integrity": True, **changes}
    monkeypatch.setattr(runner, "_run_suite", lambda *a, **kw: result)
    passed, n, failures = arena._score_heldout_counted(
        str(tmp_path), [{"code": "def test_a():\n assert True\n"}], 10, str(tmp_path))
    assert (passed, n) == (0, 1)
    assert failures[0]["verification"] == "INCONCLUSIVE"


def test_real_partial_assertion_failure_remains_a_valid_partial_score(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    held = [{"code": "import pytest\n@pytest.mark.parametrize('x', [1, 2])\ndef test_a(x):\n assert x < 2\n"}]
    passed, n, failures = arena._score_heldout_counted(str(repo), held, 30, str(tmp_path))
    assert (passed, n) == (1, 2)
    assert failures and all(f.get("verification") != "INCONCLUSIVE" for f in failures)


@pytest.mark.parametrize("lane_name", ["single", "evoforge"])
@pytest.mark.parametrize("unconfirmed", ["failed", "verification_inconclusive"])
def test_no_winner_is_declared_against_an_unconfirmed_lane(monkeypatch, lane_name, unconfirmed):
    lanes = {name: {"status": "succeeded", "outcome": "passed", "heldout": {"passed": 1, "n": 1}}
             for name in ("single", "evoforge")}
    lanes[lane_name]["heldout"]["passed"] = 0
    if unconfirmed == "failed":
        lanes[lane_name]["status"] = "failed"
    else:
        lanes[lane_name]["outcome"] = unconfirmed
    monkeypatch.setattr(arena, "find_task", lambda *a: {"goal": "x", "heldout": [{"code": "x"}]})
    monkeypatch.setattr(arena, "_run_lanes", lambda *a, **kw: (lanes["single"], lanes["evoforge"]))
    monkeypatch.setattr(arena, "_STORE", {})
    result = arena.run_arena("v2", "task", arena.BASELINE_MODEL)
    assert result["verdict"]["winner"] == "inconclusive"
    assert arena.get_arena(result["arena_id"])["verdict"]["winner"] == "inconclusive"


RISK_DIFF = "--- a/calc.py\n+++ b/calc.py\n@@ -0,0 +1 @@\n+import atexit\n"


@pytest.fixture
def screened_task(monkeypatch):
    task = {"id": "screen-test", "goal": "add a function", "files": {"calc.py": ""},
            "heldout": [{"code": "def test_a():\n assert True\n", "kind": "negative"}]}
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    monkeypatch.setattr(sealed, "_make_task_source_repo", lambda *a: ("unused", "a" * 40, []))
    monkeypatch.setattr(sealed, "_build_clean_sandbox", lambda *a: [{"check": c, "pass": True} for c in sealed.AUDIT_CHECKS])
    monkeypatch.setattr(sealed, "_apply_candidate", lambda *a, **kw: pytest.fail("screened diff must not be applied"))
    monkeypatch.setattr(runner, "_run_suite", lambda *a, **kw: pytest.fail("screened diff must not execute"))
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **kw: {
        "diff": RISK_DIFF, "tests": [], "stub": False, "model": sealed.BASELINE_MODEL,
        "usage": {"prompt_tokens": 1000000, "completion_tokens": 0}})
    ledger.reset()
    ledger.configure({"default": 100000})
    yield task
    ledger.reset()


@pytest.mark.parametrize("pipeline", [False, True])
def test_both_eval_paths_screen_before_apply_and_keep_costs(monkeypatch, screened_task, pipeline):
    monkeypatch.setattr(sealed, "load_suites", lambda *a: [{"family": "f", "tasks": [screened_task]}])
    kwargs = {"max_attempts": 1} if pipeline else {}
    result = (sealed.run_pipeline if pipeline else sealed.run_baseline)("v1", sealed.BASELINE_MODEL, **kwargs)
    assert result["scores"][0]["score"] == 0
    assert result["scores"][0]["outcome"] == "verification_inconclusive"
    assert ledger.snapshot()["spent_cents"] > 0 and ledger.snapshot()["reserved_cents"] == 0


@pytest.mark.parametrize("lane", ["single", "evoforge"])
def test_both_arena_lanes_screen_before_apply_and_keep_costs(monkeypatch, screened_task, lane):
    monkeypatch.setattr(sealed, "PIPELINE_MAX_ATTEMPTS", 1)
    result = (arena._run_single_lane if lane == "single" else arena._run_evoforge_lane)(
        screened_task, arena.BASELINE_MODEL, 10)
    assert result["outcome"] == "verification_inconclusive"
    assert result["heldout"]["passed"] == 0 and result["cost_cents"] > 0
    assert ledger.snapshot()["reserved_cents"] == 0


def test_server_repo_score_is_screened_before_runner_selection(monkeypatch):
    monkeypatch.setattr(sealed._runner_client, "runner_url", lambda: pytest.fail("no Runner selection for screened diff"))
    assert sealed._score_heldout("repo", "source", "a" * 40, RISK_DIFF, [{"code": "x"}], 10, "tmp") == 0


@pytest.mark.parametrize("lane", ["single", "evoforge"])
@pytest.mark.parametrize("missing", [False, True])
def test_cost_provenance_survives_both_lanes(monkeypatch, screened_task, lane, missing):
    monkeypatch.setattr(sealed, "PIPELINE_MAX_ATTEMPTS", 1)
    call = lambda *a: ("reservation", {"diff": RISK_DIFF}, 120, missing)
    monkeypatch.setattr(sealed, "_call_builder_task", call)
    monkeypatch.setattr(sealed, "_call_pipeline_attempt", call)
    result = (arena._run_single_lane if lane == "single" else arena._run_evoforge_lane)(
        screened_task, arena.BASELINE_MODEL, 10)
    assert result["usage_missing"] is missing and result["cost_cents"] == 120
    assert result["cost_status"] == ("estimated" if missing else "usage_reported")


def test_running_zero_cost_is_explicitly_pending():
    lane = arena._lane_skeleton("running", 2)
    assert lane["cost_status"] == "pending" and lane["usage_missing"] is None


def test_actual_http_job_keeps_inconclusive_verdict_and_cost_basis(monkeypatch):
    import time
    import main
    from fastapi.testclient import TestClient

    lanes = tuple({"status": "succeeded", "outcome": "verification_inconclusive",
                   "heldout": {"passed": 0, "n": 1}, "cost_cents": 120,
                   "usage_missing": True, "cost_status": "estimated",
                   "attempts": 1, "elapsed_ms": 1, "diff": "", "events": []}
                  for _ in range(2))
    monkeypatch.setattr(arena, "_run_lanes", lambda *a, **kw: lanes)
    monkeypatch.setattr(arena, "_STORE", {})
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **kw: pytest.fail("no model calls in HTTP contract test"))
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset()
    ledger.configure({"default": 100000})
    client = TestClient(main.app)
    try:
        response = client.post("/v1/arena", json={"suite_version": "v2", "task_id": "SV2-SS-01"})
        assert response.status_code == 202
        aid = response.json()["arena_id"]
        for _ in range(100):
            response = client.get(f"/v1/arena/{aid}")
            assert response.status_code == 200
            body = response.json()
            if body["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.01)
        assert body["status"] == "succeeded"
        assert body["verdict"]["winner"] == "inconclusive"
        assert body["lanes"]["single"]["cost_status"] == "estimated"
        assert body["lanes"]["evoforge"]["usage_missing"] is True
    finally:
        ledger.reset()
