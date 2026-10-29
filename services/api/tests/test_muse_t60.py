"""T60 — equal-tools comparison: single_apply strict|tolerant."""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import evolution_rounds as ev  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


def _overcount(diff: str) -> str:
    return re.sub(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@",
                  lambda m: "@@ -%s,%d +%s,%d @@" % (
                      m.group(1), int(m.group(2)) + 1,
                      m.group(3), int(m.group(4)) + 1),
                  diff, flags=re.M)


def test_manifest_records_single_apply_and_comparison():
    base = {"board.py": "x\n"}
    rounds = [{"goal": "g", "heldout": []}]
    m = ev.build_manifest("a", "t", 1, base, rounds, "muse-spark-1.3", "critic")
    assert m["single_apply"] == "strict" and m["comparison"] == "chat_vs_system"
    assert m["lanes"]["single"] == {"model": "muse-spark-1.3",
                                    "harness": "api-sealed-eval/1",
                                    "max_attempts": 1, "feedback": "none",
                                    "apply": "strict"}
    assert m["lanes"]["evoforge"]["apply"] == "tolerant"
    assert "strict" in m["disclosure"] or "chat_vs_system" in m["disclosure"]
    m2 = ev.build_manifest("a", "t", 1, base, rounds, "muse-spark-1.3",
                           "critic", "tolerant")
    assert m2["single_apply"] == "tolerant" and m2["comparison"] == "equal_tools"
    assert m2["lanes"]["single"]["harness"] == "api-sealed-eval/2"
    assert m2["lanes"]["single"]["apply"] == "tolerant"
    assert "tolerant" in m2["disclosure"] or "equal_tools" in m2["disclosure"]


def test_tolerant_single_applies_overcounted_diff_strict_does_not(monkeypatch):
    old = {"board.py": "line1\nline2\nline3\n"}
    new = {"board.py": "line1\nLINE2\nline3\n"}
    diff = "".join(difflib.unified_diff(
        old["board.py"].splitlines(True), new["board.py"].splitlines(True),
        "a/board.py", "b/board.py"))
    over = _overcount(diff)
    from evoforge import sealed_eval as se
    monkeypatch.setattr(se, "_call_builder_task",
                        lambda goal, base, fc: ("r", {"diff": over, "rationale": "x"}, 5, False))
    monkeypatch.setattr(ev, "_score_and_preview",
                        lambda *a, **k: (0, 1, [], 0, 1,
                                         {"preview_html": "", "preview_sha": "sha256:" + "0" * 64,
                                          "preview_error": "e"}, None))
    _, strict = ev._run_single_round({"index": 1, "goal": "g", "heldout": []},
                                     [], dict(old), 10, "strict")
    _, tolerant = ev._run_single_round({"index": 1, "goal": "g", "heldout": []},
                                       [], dict(old), 10, "tolerant")
    assert strict["attempts"] == 1 and tolerant["attempts"] == 1
    assert strict["status"] == "FAILED"
    assert tolerant["status"] != "FAILED"


def test_stats_single_apply_filter_and_validation():
    ev.clear()
    try:
        def _doc(rid, sa=None):
            d = {"run_id": rid, "app_id": "mission_board", "status": "succeeded",
                 "feedback": "critic", "created_at": 1.0, "finished_at": 2.0,
                 "manifest": {"app_id": "mission_board", "rounds": 1},
                 "rounds": [{"index": 1, "name": "R1",
                             "sides": {"evoforge": {"status": "READY", "verified": True,
                                                    "cost_cents": 10},
                                       "single": {"status": "READY", "verified": True,
                                                  "cost_cents": 5}}}]}
            if sa is not None:
                d["single_apply"] = sa
            return d
        ev._save(_doc("t60_a"))
        ev._save(_doc("t60_b", "tolerant"))
        assert c.get("/v1/evolution/stats", params={"single_apply": "bogus"}).status_code == 422
        assert c.post("/v1/evolution/runs",
                      json={"app_id": "mission_board", "single_apply": "bogus"}).status_code == 422
        assert ev.stats(single_apply="strict")["runs"] == 1
        assert ev.stats(single_apply="tolerant")["runs"] == 1
        assert c.get("/v1/evolution/stats", params={"single_apply": "strict"}).json()["runs"] == 1
        assert c.get("/v1/evolution/stats", params={"single_apply": "tolerant"}).json()["runs"] == 1
    finally:
        ev.clear()
