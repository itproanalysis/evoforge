"""T79 equal-tools scoreboard split (API + web labels)."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import arena as arena_mod  # noqa: E402
from evoforge import commands, eval_jobs, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


def setup_function(_fn):
    ledger.reset()
    ledger.configure({"default": 500000})
    commands.reset()
    eval_jobs.clear()
    arena_mod.clear()


def teardown_function(_fn):
    eval_jobs.clear()
    arena_mod.clear()
    ledger.reset()
    ledger.configure({"default": 500000})


def _doc(aid, status, winner, sp=0, sn=0, ep=0, en=0,
         sc=0, ec=0, judge=0, apply=None):
    doc = {"arena_id": aid, "status": status,
           "suite_version": "v2", "task_id": "T",
           "model": "muse-spark-1.3",
           "goal": "g", "feedback": "critic",
           "created_at": time.time(), "started_at": time.time(),
           "finished_at": time.time(),
           "judge_cost_cents": judge,
           "lanes": {"single": {"status": "succeeded", "attempts": 1,
                                "heldout": {"passed": sp, "n": sn},
                                "outcome": "passed", "cost_cents": sc,
                                "elapsed_ms": 1, "diff": "", "events": []},
                     "evoforge": {"status": "succeeded", "attempts": 1,
                                  "heldout": {"passed": ep, "n": en},
                                  "outcome": "passed", "cost_cents": ec,
                                  "elapsed_ms": 1, "diff": "", "events": []}},
           "verdict": {"winner": winner, "reason": "t"}, "error": None}
    if apply is not None:
        doc["manifest"] = {"lanes": {"single": {"apply": apply}}}
    return doc


def test_equal_tools_empty_zeros_and_existing_fields_kept():
    body = c.get("/v1/arena/summary").json()
    eq = {k: v for k, v in body["equal_tools"].items() if k != "stats"}  # T81 adds "stats"
    assert eq == {
        "scored": 0,
        "wins": {"evoforge": 0, "single": 0, "tie": 0},
        "heldout": {"single": {"passed": 0, "n": 0},
                    "evoforge": {"passed": 0, "n": 0}},
        "cost_cents": {"single": 0, "evoforge": 0, "judge": 0},
    }
    for key in ("total", "running", "failed", "scored", "unscorable",
                "inconclusive", "wins", "heldout", "cost_cents", "basis"):
        assert key in body


def test_equal_tools_counts_only_tolerant_scored():
    arena_mod._save(_doc("s1", "succeeded", "evoforge", 1, 2, 2, 2, 10, 20, 5,
                         apply="strict"))
    arena_mod._save(_doc("s2", "succeeded", "tie", 0, 1, 0, 1, 3, 4, 0,
                         apply=None))
    arena_mod._save(_doc("e1", "succeeded", "single", 2, 2, 1, 2, 7, 8, 2,
                         apply="tolerant"))
    arena_mod._save(_doc("e2", "succeeded", "unscorable", 9, 9, 9, 9, 99, 99, 7,
                         apply="tolerant"))
    bad = _doc("e3", "failed", "inconclusive", apply="tolerant")
    bad["lanes"]["single"]["status"] = "failed"
    arena_mod._save(bad)
    body = c.get("/v1/arena/summary").json()
    assert body["scored"] == 3
    eq = body["equal_tools"]
    assert eq["scored"] == 1
    assert eq["wins"] == {"evoforge": 0, "single": 1, "tie": 0}
    assert eq["heldout"] == {"single": {"passed": 2, "n": 2},
                             "evoforge": {"passed": 1, "n": 2}}
    assert eq["cost_cents"] == {"single": 7, "evoforge": 8, "judge": 2}


def test_arena_job_result_redacts_diffs_and_events(monkeypatch):
    """The eval-jobs copy of an arena must not serve candidate patch text.

    Full lane diffs + event streams stay in the arena store
    (GET /v1/arena/{id}); the job result keeps verdict, scores, costs
    and manifest only, so completed arena jobs in GET /v1/eval/jobs can
    never leak "+++ " or reference fixes into sealed-eval job responses.
    """
    import copy

    task = {"id": "T", "goal": "g", "files": {"a.py": ""}, "heldout": []}
    monkeypatch.setattr(arena_mod, "find_task", lambda *a: task)
    lane = {"status": "succeeded", "attempts": 1,
            "heldout": {"passed": 1, "n": 1}, "outcome": "passed",
            "cost_cents": 5, "usage_missing": False,
            "cost_status": "usage_reported", "elapsed_ms": 1,
            "diff": "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n",
            "events": [{"seq": 1, "ts": 0.0, "role": "builder",
                        "message": "m +++ leak"}],
            "preview_source": "none"}
    monkeypatch.setattr(arena_mod, "_run_lanes",
                        lambda *a, **kw: (copy.deepcopy(lane),
                                          copy.deepcopy(lane)))
    monkeypatch.setattr(arena_mod, "build_manifest",
                        lambda *a, **kw: {"lanes": {"single": {
                            "apply": "tolerant"}}})
    res = arena_mod.run_arena("v2", "T", "muse-spark-1.3",
                              arena_id="aid_t79_job")
    assert "+++ " not in json.dumps(res)
    assert res["verdict"]["winner"] == "tie"
    assert res["lanes"]["single"]["diff"] == ""
    assert res["lanes"]["single"]["events"] == []
    full = arena_mod.get_arena("aid_t79_job")
    assert "+++ " in full["lanes"]["single"]["diff"]
    assert len(full["lanes"]["single"]["events"]) == 1


def test_web_labels_and_scoreboards():
    for loc in ("en", "ko"):
        raw = (Path(__file__).resolve().parents[3] / "apps" / "web"
               / "messages" / f"{loc}.json").read_text(encoding="utf-8")
        msgs = json.loads(raw)
        assert str(msgs["arena"].get("summary-equal-tools", "")).strip()
    root = Path(__file__).resolve().parents[3] / "apps" / "web"
    arena_src = (root / "app" / "[locale]" / "arena" / "page.tsx").read_text(
        encoding="utf-8")
    home_src = (root / "app" / "[locale]" / "page.tsx").read_text(
        encoding="utf-8")
    for src in (arena_src, home_src):
        assert 'summary-equal-tools' in src
        first_eq = src.index("summary-equal-tools")
        assert "equal_tools" in src
        assert "summary-all-matches" in src
        assert first_eq < src.index("summary-all-matches")
    api_src = (root / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "equal_tools" in api_src
