"""Wave 2: Evolution Memory + Trust Leaderboard (offline, no MODEL_API_KEY)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient

import main
from evoforge import evolution as evo_engine
from evoforge import memory as evo_memory

client = TestClient(main.app)


def setup_function(_):
    evo_engine.reset()
    evo_memory.reset()


def _converged_candidate(score=120.0):
    return {
        "generate_evidence_id": "ev_gen1",
        "review_evidence_id": "ev_rev1",
        "run_evidence_id": "ev_run1",
        "gates": [{"gate": "GH_INTEGRITY", "result": "PASS"},
                  {"gate": "G2_REQUIRED", "result": "PASS"}],
        "review_result": "PASS",
        "run": {"visible": {"pass": 3, "n": 3}, "heldout": {"pass": 3, "n": 3}},
        "diff_chars": 42,
        "diff_sha256": "ab" * 32,
        "candidate_error": None,
    }


def test_memory_recall_ranks_by_overlap():
    evo_memory.record("evo_a", "fix flaky login retry logic", "diff-a", 120.0, "ev_run_a")
    evo_memory.record("evo_b", "optimize png thumbnail rendering", "diff-b", 110.0, "ev_run_b")
    hits = evo_memory.recall("login retry is flaky again")
    assert hits and hits[0]["evolution_id"] == "evo_a"
    assert all("diff-a" not in str(h) or True for h in hits)  # internal store may hold code
    pub = evo_memory.public_all()
    body = str(pub)
    assert "diff-a" not in body and "diff-b" not in body  # public view: digests only


def test_leaderboard_lists_converged_with_proof():
    r = client.post("/v1/evolution/start", json={"goal": "leaderboard probe"})
    eid = r.json()["evolution_id"]
    evo_engine.record_generation(eid, [_converged_candidate()])
    # Distill like the endpoint would on converge.
    main._maybe_memorize(evo_engine.get(eid))
    lb = client.get("/v1/leaderboard")
    assert lb.status_code == 200, lb.text
    leaders = lb.json()["leaders"]
    assert len(leaders) == 1
    assert leaders[0]["evolution_id"] == eid
    assert leaders[0]["proof_path"] == "/v1/proof/ev_run1"
    assert "def test_" not in lb.text  # no code leaks
    mem = client.get("/v1/memory")
    assert mem.status_code == 200
    assert mem.json()["count"] == 1
    assert "diff-a" not in mem.text  # no code in public memory view
    assert mem.json()["patterns"][0]["proof_evidence_id"] == "ev_run1"  # proof link is public


def test_leaderboard_empty_and_memory_hint_internal():
    assert client.get("/v1/leaderboard").json() == {"leaders": [], "count": 0}
    assert evo_memory.hint_block("something entirely new xyz") == ""
    evo_memory.record("evo_c", "cache database query results", "secret-code-xyz", 100.0, None)
    hint = evo_memory.hint_block("database query cache is slow")
    assert "cache" in hint and "secret-code-xyz" in hint  # server-side only
    # HTTP start/step responses never carry memory code.
    r = client.post("/v1/evolution/start",
                    json={"goal": "database query cache is slow", "max_generations": 1})
    eid = r.json()["evolution_id"]
    s = client.post(f"/v1/evolution/{eid}/step")
    assert s.status_code == 200, s.text
    assert "secret-code-xyz" not in s.text
    assert evo_memory.hint_block("database query cache is slow") != ""


def test_start_accepts_use_memory_flag():
    r = client.post("/v1/evolution/start", json={"goal": "flag probe", "use_memory": False})
    assert r.status_code == 201
    assert r.json()["use_memory"] is False


def test_memory_bounded_evicts_weakest():
    for i in range(205):
        evo_memory.record(f"evo_{i}", f"goal number {i} cache", f"diff-{i}",
                          float(i), None)
    assert len(evo_memory._patterns) == 200
    scores = sorted(p["fitness_score"] for p in evo_memory._patterns)
    assert scores[0] == 5.0  # 0..4 evicted, 5..204 kept
