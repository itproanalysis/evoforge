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
    # /run is asynchronous since T31 (the web proxy cuts requests at 300 s): 202, then poll to the end.
    done = client.post(f"/v1/evolution/{eid}/run")
    assert done.status_code in (200, 202), done.text
    import time as _t
    for _ in range(300):
        body = client.get(f"/v1/evolution/{eid}").json()
        if body["status"] != "RUNNING" and not body.get("run_active"):
            break
        _t.sleep(0.1)
    assert body["status"] == "EXHAUSTED"
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


def _mint_signing_key(monkeypatch) -> str:
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    b64 = base64.b64encode(raw).decode("ascii")
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", b64)
    return b64


def test_proof_certificate_redacted_and_verifiable(monkeypatch):
    _mint_signing_key(monkeypatch)
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


def test_step_lock_rejects_concurrent_generation():
    r = client.post("/v1/evolution/start", json={"goal": "lock probe", "max_generations": 1})
    eid = r.json()["evolution_id"]
    lock = evo_engine.lock_for(eid)
    assert lock.acquire(blocking=False)
    try:
        s = client.post(f"/v1/evolution/{eid}/step")
        assert s.status_code == 409, s.text
        assert "already has a running generation" in s.text
    finally:
        lock.release()
    # After release the step proceeds normally (offline stub path).
    s = client.post(f"/v1/evolution/{eid}/step")
    assert s.status_code == 200, s.text


def test_start_source_repo_passthrough_and_validation():
    r = client.post("/v1/evolution/start", json={"goal": "repo probe", "source_repo": ""})
    assert r.status_code == 201
    assert r.json()["source_repo"] == ""
    bad = client.post("/v1/evolution/start",
                      json={"goal": "repo probe", "source_repo": "C:/no/such/repo_xyz"})
    assert bad.status_code == 400


def test_case_w10_weak_oracle_diagnosis_and_feedback():
    # Empirical Case W10: weak oracle (tautology / ratio < 0.8) yields weak_oracle classification
    cand = {
        "gates": [{"gate": "GH_INTEGRITY", "result": "INCONCLUSIVE", "reason": "strong fraction 0.67 < 0.8"}],
        "run": {"visible": {"pass": 3, "n": 3}, "heldout": {"pass": 4, "n": 4}},
    }
    assert evo_engine.classify_failure(cand) == "weak_oracle"

    gen = {"index": 1, "candidates": [cand]}
    feedback = evo_engine.feedback_goal("Divide function", gen)
    assert "ORACLE INTEGRITY RULE (Case W10)" in feedback
    assert "pytest.raises" in feedback

    # Bounded retention test (stability)
    evo_engine.reset()
    for i in range(105):
        evo = evo_engine.start(f"goal {i}", max_generations=1)
        evo["status"] = "EXHAUSTED"
    assert len(evo_engine.list_all()) == 100


def test_step_local_source_repo_context(tmp_path, monkeypatch):
    """Regression: target_paths + local source_repo must load context (no remote)."""
    import subprocess

    repo = tmp_path / "case"
    repo.mkdir()
    (repo / "calc.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=str(repo), check=True, timeout=60)
    monkeypatch.setenv("EVO_REPO_ROOTS", str(repo))
    r = client.post("/v1/evolution/start", json={
        "goal": "context probe", "repo_ref": "HEAD", "source_repo": str(repo),
        "target_paths": ["calc.py"], "max_generations": 1, "population": 1})
    assert r.status_code == 201, r.text
    s = client.post(f"/v1/evolution/{r.json()['evolution_id']}/step")
    assert s.status_code == 200, s.text
    assert s.json()["winner"]["generate_evidence_id"]
