"""Claude — cloud review A2 (2026-10-30): Critic-feedback evolution runs stored the held-out-feedback disclosure; they
are served with the correct sentence (flagged), new runs store it, and stats carry a paired per-round sign test."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from evoforge import evolution_rounds as er  # noqa: E402


def _run(rid, fb, pairs):
    return {"run_id": rid, "kind": er.KIND, "status": "succeeded", "feedback": fb, "created_at": 1.0,
            "manifest": {"single_apply": "tolerant", "disclosure": er._disclosure_for("tolerant", "heldout")},
            "rounds": [{"index": i + 1, "sides": {"evoforge": {"status": "READY" if e else "FAILED", "cost_cents": 3},
                                                  "single": {"status": "READY" if s else "FAILED", "cost_cents": 1}}}
                       for i, (e, s) in enumerate(pairs)]}


def test_critic_runs_are_served_with_the_critic_disclosure():
    er.clear()
    store = er._store()
    store["r1"] = {"id": "r1", "kind": er.KIND, "evolution_run": _run("r1", "critic", [(1, 1)])}
    store["r2"] = {"id": "r2", "kind": er.KIND, "evolution_run": _run("r2", "heldout", [(1, 1)])}
    d1, d2 = er.get_run("r1"), er.get_run("r2")
    assert "no held-out signal" in d1["manifest"]["disclosure"] and d1["manifest"]["disclosure_corrected"] is True
    assert "upper-bound oracle" in d2["manifest"]["disclosure"] and "disclosure_corrected" not in d2["manifest"]
    assert "no held-out signal" in er._disclosure_for("tolerant", "critic")
    assert all("upper-bound" not in r["manifest"]["disclosure"] for r in er.list_runs() if r["feedback"] == "critic")
    er.clear()


def test_stats_include_a_paired_sign_test():
    er.clear()
    store = er._store()
    store["r1"] = {"id": "r1", "kind": er.KIND, "evolution_run": _run("r1", "critic", [(1, 0), (1, 0), (1, 1), (0, 0), (1, 0)])}
    p = er.stats("critic")["paired"]
    assert (p["evoforge_only"], p["single_only"], p["both"], p["neither"]) == (3, 0, 1, 1)
    assert abs(p["sign_test_p"] - 0.25) < 1e-9 and p["significant"] is False
    er.clear()
