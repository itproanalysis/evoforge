"""T27: really-signed proof certificates + evolution worst-case budget cap."""
import base64
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


def _gen_key_b64() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    return base64.b64encode(raw).decode("ascii")


def _sample_body():
    return {
        "gates": [{"gate": "GH_INTEGRITY", "result": "PASS", "reason": ""}],
        "diff_sha256": "ab" * 32,
        "sealed_kinds": [],
        "sealed_count": 0,
        "model": "muse-spark-1.3",
    }, [{"stage": "Gate", "event_id": "evt_1"}]


def test_mint_signed_roundtrip(monkeypatch):
    key = _gen_key_b64()
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", key)
    pub_ev, chain = _sample_body()
    cert = proof_mod.mint("ev_x", pub_ev, chain)
    assert cert["signed"] is True
    assert cert["algorithm"] == "Ed25519"
    assert isinstance(cert["signature"], str) and cert["signature"]
    assert isinstance(cert["public_key"], str) and cert["public_key"]
    assert proof_mod.verify(cert)["ok"] is True


def test_mint_tamper_rejected(monkeypatch):
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", _gen_key_b64())
    pub_ev, chain = _sample_body()
    cert = proof_mod.mint("ev_x", pub_ev, chain)
    for field, bad in (("verdict", "NOT_VERIFIED"), ("evidence_id", "ev_other"),
                       ("diff_sha256", "ff" * 32), ("model", "evil")):
        t = dict(cert)
        t[field] = bad
        assert proof_mod.verify(t)["ok"] is False, field
    # Recomputing a digest over edited bytes must not pass as a signature.
    import hashlib
    import json

    t = dict(cert)
    t["verdict"] = "NOT_VERIFIED"
    canon = json.dumps({k: v for k, v in t.items()
                        if k not in ("signature", "public_key", "algorithm", "signed")},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    t["signature"] = hashlib.sha256(canon.encode()).hexdigest()
    assert proof_mod.verify(t)["ok"] is False


def test_verify_wrong_key_rejected(monkeypatch):
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", _gen_key_b64())
    pub_ev, chain = _sample_body()
    cert = proof_mod.mint("ev_x", pub_ev, chain)
    # Attacker re-signs with their own key but server still checks its own.
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", _gen_key_b64())
    assert proof_mod.verify(cert)["ok"] is False
    # A cert carrying another key is rejected even if the body is untouched:
    # verify trusts the server key, not the key inside the cert.
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", _gen_key_b64())
    pub_ev2, chain2 = _sample_body()
    cert2 = proof_mod.mint("ev_x", pub_ev2, chain2)
    evil = dict(cert2)
    evil["public_key"] = cert["public_key"]
    assert proof_mod.verify(evil)["ok"] is False  # wrong key named inside
    # Attacker re-signs the body with their own key: also rejected.
    import json as _json

    from cryptography.hazmat.primitives import serialization as _ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey as _Priv,
    )

    atk = _Priv.generate()
    atk_pub = base64.b64encode(atk.public_key().public_bytes(
        _ser.Encoding.Raw, _ser.PublicFormat.Raw)).decode("ascii")
    forged = dict(cert2)
    forged["verdict"] = "NOT_VERIFIED"
    forged["public_key"] = atk_pub
    forged["signature"] = base64.b64encode(atk.sign(_json.dumps(
        {k: v for k, v in forged.items()
         if k not in ("signature", "public_key", "algorithm", "signed")},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode())).decode("ascii")
    assert proof_mod.verify(forged)["ok"] is False
    evil2 = dict(cert2)
    evil2["verdict"] = "NOT_VERIFIED"
    evil2["public_key"] = cert2["public_key"]
    assert proof_mod.verify(evil2)["ok"] is False


def test_unsigned_when_no_key(monkeypatch):
    monkeypatch.delenv("EVO_PROOF_SIGNING_KEY", raising=False)
    pub_ev, chain = _sample_body()
    cert = proof_mod.mint("ev_x", pub_ev, chain)
    assert cert["signed"] is False
    assert cert["signature"] is None
    assert cert["algorithm"] is None
    assert cert["public_key"] is None
    assert proof_mod.verify(cert)["ok"] is False


def test_proof_key_endpoint(monkeypatch):
    monkeypatch.delenv("EVO_PROOF_SIGNING_KEY", raising=False)
    assert client.get("/v1/proof/key").status_code == 404
    key = _gen_key_b64()
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", key)
    r = client.get("/v1/proof/key")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["algorithm"] == "Ed25519"
    assert body["public_key"] == proof_mod.server_public_key_b64()
    g = client.post("/v1/gates/evaluate", json={
        "diff": "--- a\n+++ b\n@@\n+x", "tests": [],
        "heldout_kinds": [], "vis_pass": 0, "vis_n": 0,
        "held_pass": 0, "held_n": 0})
    evid = g.json()["evidence_id"]
    cert = client.get(f"/v1/proof/{evid}").json()
    assert cert["public_key"] == body["public_key"]
    assert cert["verify"]["ok"] is True


def test_evolution_start_budget_cap_default(monkeypatch):
    monkeypatch.delenv("EVO_EVOLUTION_MAX_CENTS", raising=False)
    before = client.get("/v1/evolution").json()["evolutions"]
    r = client.post("/v1/evolution/start", json={
        "goal": "spend it all", "max_generations": 10, "population": 5})
    assert r.status_code == 402, r.text
    worst = 10 * 5 * 2 * main.COST_CENTS
    assert str(worst) in r.text and "1500" in r.text
    after = client.get("/v1/evolution").json()["evolutions"]
    assert len(after) == len(before)  # nothing created
    ok = client.post("/v1/evolution/start", json={
        "goal": "small probe", "max_generations": 1, "population": 1})
    assert ok.status_code == 201, ok.text


def test_evolution_start_custom_cap(monkeypatch):
    monkeypatch.setenv("EVO_EVOLUTION_MAX_CENTS", "12000")
    r = client.post("/v1/evolution/start", json={
        "goal": "big run", "max_generations": 10, "population": 5})
    assert r.status_code == 201, r.text
    monkeypatch.setenv("EVO_EVOLUTION_MAX_CENTS", "100")
    r2 = client.post("/v1/evolution/start", json={
        "goal": "tiny over", "max_generations": 1, "population": 1})
    assert r2.status_code == 402, r2.text
    assert str(1 * 1 * 2 * main.COST_CENTS) in r2.text
