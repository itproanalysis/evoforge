"""T30 memory-mode unit tests: evolution + memory keep today's shapes without Postgres."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import evolution as evo  # noqa: E402
from evoforge import memory as mem  # noqa: E402


def setup_function(_):
    for key in ("EVO_STATE_BACKEND", "DATABASE_URL"):
        os.environ.pop(key, None)
    os.environ["EVO_STATE_BACKEND"] = "memory"
    evo.reset()
    mem.reset()


def _passing_candidate():
    gates = [{"gate": "G0", "result": "PASS"}, {"gate": "G1", "result": "PASS"}]
    run = {"visible": {"pass": 1, "n": 1}, "heldout": {"pass": 2, "n": 2}}
    return {"gates": gates, "run": run, "generate_evidence_id": "ev_1",
            "review_evidence_id": "ev_2", "run_evidence_id": "ev_3",
            "diff_chars": 10, "diff_sha256": "x" * 64}


def test_start_get_list_shapes():
    e = evo.start("fix login", "HEAD", ["a.py"], 3, 2, True, "")
    assert e["evolution_id"].startswith("evo_") and e["status"] == "RUNNING"
    assert evo.get(e["evolution_id"])["goal"] == "fix login"
    assert [x["evolution_id"] for x in evo.list_all()] == [e["evolution_id"]]
    assert evo.get("evo_missing") is None


def test_start_validation():
    with pytest.raises(ValueError):
        evo.start(" ", "HEAD")
    with pytest.raises(ValueError):
        evo.start("g", " ")
    with pytest.raises(ValueError):
        evo.start("g", "HEAD", max_generations=0)
    with pytest.raises(ValueError):
        evo.start("g", "HEAD", population=6)


def test_record_generation_converges_and_best():
    e = evo.start("goal here", "HEAD", max_generations=2, population=1)
    gen = evo.record_generation(e["evolution_id"], [_passing_candidate()])
    assert gen["converged"] is True and gen["index"] == 0
    assert evo.get(e["evolution_id"])["status"] == "CONVERGED"
    assert evo.get(e["evolution_id"])["best"]["fitness"]["all_pass"] is True
    with pytest.raises(ValueError):
        evo.record_generation(e["evolution_id"], [_passing_candidate()])
    with pytest.raises(KeyError):
        evo.record_generation("evo_missing", [])


def test_record_generation_exhausts():
    e = evo.start("goal here", "HEAD", max_generations=1, population=1)
    cand = {"gates": [{"gate": "G0", "result": "FAIL"}], "run": None}
    gen = evo.record_generation(e["evolution_id"], [cand])
    assert gen["converged"] is False
    assert evo.get(e["evolution_id"])["status"] == "EXHAUSTED"


def test_cancel_and_public_view():
    e = evo.start("goal here", "HEAD")
    out = evo.cancel(e["evolution_id"])
    assert out["status"] == "CANCELLED"
    assert evo.cancel(e["evolution_id"])["status"] == "CANCELLED"
    with pytest.raises(KeyError):
        evo.cancel("evo_missing")
    view = evo.public(out)
    assert view["evolution_id"] == e["evolution_id"] and view["status"] == "CANCELLED"
    assert evo.lock_for(e["evolution_id"]) is evo.lock_for(e["evolution_id"])


def test_fitness_and_classify_and_feedback():
    fit = evo.fitness([{"result": "PASS"}, {"result": "PASS"}], None)
    assert fit["all_pass"] is True and fit["score"] >= 100
    assert evo.classify_failure({"gates": [{"gate": "GH_INTEGRITY", "result": "FAIL"}]}) == "weak_oracle"
    assert evo.classify_failure({"gates": [{"gate": "G", "result": "PASS"}]}) == "none"
    goal = evo.feedback_goal("do it", {"index": 0, "candidates": [
        {"gates": [{"gate": "GH_INTEGRITY", "result": "FAIL", "reason": "weak"}], "review_result": "PASS"}]})
    assert "ORACLE INTEGRITY" in goal
    assert evo.feedback_goal("do it", {"index": 0, "candidates": []}) == "do it"


def test_memory_record_recall_hint_public():
    p = mem.record("evo_1", "fix login flow", "diff-body", 120.0, "ev_run")
    assert p["evolution_id"] == "evo_1" and p["keywords"]
    assert mem.record("evo_1", "other", "x", 1.0, None) is p
    hits = mem.recall("login flow broke")
    assert [h["evolution_id"] for h in hits] == ["evo_1"]
    assert "login" in mem.hint_block("login flow broke")
    assert mem.hint_block("zzzqqq") == ""
    pub = mem.public_all()
    assert pub[0]["pattern_id"] == p["pattern_id"] and pub[0]["proof_path"] == "/v1/proof/ev_run"
    assert "diff-body" not in str(pub)


def test_reset_clears_memory_mode():
    evo.start("g", "HEAD")
    mem.record("evo_1", "goal words", "d", 1.0, None)
    evo.reset()
    mem.reset()
    assert evo.list_all() == [] and mem.public_all() == [] and mem.recall("goal") == []
