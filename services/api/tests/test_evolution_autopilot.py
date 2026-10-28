"""Autopilot evolution + proof certificates (offline, no MODEL_API_KEY)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient

import main
from evoforge import evolution as evo_engine
from evoforge import proof as proof_mod

client = TestClient(main.app)


def setup_function(_):
    evo_engine.reset()


def test_start_step_exhausted_offline():
    r = client.post("/v1/evolution/start", json={
        "goal": "offline autopilot probe", "repo_ref": "HEAD",
        "max_generations": 2, "population": 1})
    assert r.status_code == 201, r.text
    eid = r.json()["evolution_id"]
    # One step: stub Builder + stub Critic -> candidate recorded, no run, no crash.
    s = client.post(f"/v1/evolution/{eid}/step")
    assert s.status_code == 200, s.text
    body = s.json()
    assert body["generation"] == 0
    assert body["winner"]["generate_evidence_id"]
    assert body["winner"]["run_evidence_id"] is None  # stub review can't back a run
    assert body["winner"]["candidate_error"] is not None
    # Full run exhausts honestly (never fake-converges offline).
    done = client.post(f"/v1/evolution/{eid}/run")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "EXHAUSTED"
    detail = client.get(f"/v1/evolution/{eid}")
    assert detail.json()["status"] == "EXHAUSTED"
    assert len(detail.json()["generations"]) == 2


def test_promote_blocked_without_verified_run():
    r = client.post("/v1/evolution/start", json={"goal": "x", "max_generations": 1})
    eid = r.json()["evolution_id"]
    p = client.post(f"/v1/evolution/{eid}/promote")
    assert p.status_code == 409


def test_fitness_scoring_unit():
    full = [{"gate": "GH_INTEGRITY", "result": "PASS"},
            {"gate": "G2_REQUIRED", "result": "PASS"}]
    run = {"visible": {"pass": 3, "n": 3}, "heldout": {"pass": 3, "n": 3}}
    f = evo_engine.fitness(full, run)
    assert f["all_pass"] is True and f["score"] >= 100
    bad = evo_engine.fitness([{"gate": "GH_INTEGRITY", "result": "FAIL", "reason": "x"}], None)
    assert bad["all_pass"] is False and bad["score"] < 100


def test_feedback_goal_carries_failures():
    gen = {"index": 0, "candidates": [
        {"gates": [{"gate": "G2_REQUIRED", "result": "FAIL", "reason": "no exec"}],
         "review_result": "FAIL"}]}
    nxt = evo_engine.feedback_goal("make it fast", gen)
    assert "G2_REQUIRED" in nxt and "make it fast" in nxt


def test_proof_certificate_redacted_and_verifiable():
    g = client.post("/v1/gates/evaluate", json={
        "diff": "--- a\n+++ b\n@@\n+x", "tests": [{"code": "def test_x(): assert 1 == 1"}],
        "heldout_kinds": [], "vis_pass": 0, "vis_n": 0, "held_pass": 0, "held_n": 0})
    evid = g.json()["evidence_id"]
    p = client.get(f"/v1/proof/{evid}")
    assert p.status_code == 200, p.text
    cert = p.json()
    assert cert["evidence_id"] == evid
    assert cert["verify"]["ok"] is True
    assert cert["verdict"] in ("VERIFIED", "NOT_VERIFIED")
    body = p.text
    assert "assert 1 == 1" not in body  # no code leaks into the certificate
    tampered = dict(cert)
    tampered["verdict"] = "VERIFIED"
    assert proof_mod.verify(tampered)["ok"] is False


def test_proof_unknown_404():
    assert client.get("/v1/proof/ev_nope123").status_code == 404
