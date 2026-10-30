"""Claude — cloud review A1/A3 (2026-10-30): one fair basis for the headline numbers. Matches with the strict single-lane
patch rule or with held-out failing-test names fed to EvoForge stay in "all matches" but are excluded (and counted) from
the fair block; the fair block also states what the extra cost bought."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import arena  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


def _doc(aid, winner, s, e, apply, fb, sc=5, ec=20):
    return {"arena_id": aid, "status": "succeeded", "created_at": 1.0, "verdict": {"winner": winner, "reason": "x"},
            "manifest": {"lanes": {"single": {"apply": apply}, "evoforge": {"feedback": fb}}},
            "lanes": {"single": {"heldout": {"passed": s, "n": 3}, "cost_cents": sc},
                      "evoforge": {"heldout": {"passed": e, "n": 3}, "cost_cents": ec}}}


def test_fair_block_excludes_strict_and_oracle_and_states_value():
    arena.clear()
    store = arena._store()
    docs = [_doc("f1", "evoforge", 0, 3, "tolerant", "critic"), _doc("f2", "evoforge", 1, 3, "tolerant", "critic"),
            _doc("f3", "tie", 3, 3, "tolerant", "critic"),
            _doc("s1", "evoforge", 0, 3, "strict", "critic"),
            _doc("o1", "evoforge", 0, 3, "tolerant", "heldout_failing_test_names")]
    for d in docs:
        store[f"arena-{d['arena_id']}"] = {"id": f"arena-{d['arena_id']}", "kind": arena.KIND, "arena": d}
    s = c.get("/v1/arena/summary").json()
    assert s["wins"] == {"evoforge": 4, "single": 0, "tie": 1}  # all matches unchanged
    eq = s["equal_tools"]
    assert eq["wins"] == {"evoforge": 2, "single": 0, "tie": 1}
    assert eq["excluded"] == {"strict_harness": 1, "oracle_feedback": 1}
    assert eq["value"] == {"extra_solved": 2, "extra_cost_cents": 45, "cents_per_extra_solved": 23}
    assert "held-out" in eq["basis"] and "sign test" in eq["basis"]
    arena.clear()
