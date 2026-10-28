"""Critic acceptance (sealed during build, promoted after) — T27: proof certificates are really signed (Ed25519), and an evolution's worst-case cost is
refused up front.

Review of de481a8/f4de75d: `signature = sha256(canonical JSON)` is a digest anyone can recompute after editing the
certificate, so "tamper-evident / SSL certificate for AI code" did not hold. And /v1/evolution/start accepted
10 generations x 5 candidates (up to 100 model calls, 12000c reserved) with no cap."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import evolution as evo_engine, ledger  # noqa: E402
from evoforge import proof as proof_mod  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


def _key_b64(priv: Ed25519PrivateKey) -> str:
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return base64.b64encode(raw).decode()


@pytest.fixture
def signing_key(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", _key_b64(priv))
    return priv


@pytest.fixture(autouse=True)
def fresh():
    evo_engine.reset()
    ledger.reset()
    ledger.configure({"default": 500000})


def _public_view():
    return {"gates": [{"gate": "GH_INTEGRITY", "result": "PASS", "reason": "ok"},
                      {"gate": "G2_REQUIRED", "result": "PASS", "reason": "ok"}],
            "diff_sha256": "ab" * 32, "sealed_kinds": ["negative"], "sealed_count": 1, "model": "muse-spark-1.3"}


def _canonical_without_signature(cert):
    body = {k: v for k, v in cert.items() if k not in ("signature", "public_key", "algorithm", "signed")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


# ---- real signatures ----

def test_minted_certificate_is_ed25519_signed_and_verifies_with_the_public_key(signing_key):
    cert = proof_mod.mint("ev_1", _public_view(), [{"stage": "Run", "event_id": "ev_1"}])
    assert cert["algorithm"] == "Ed25519" and cert["signed"] is True
    pub = signing_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert base64.b64decode(cert["public_key"]) == pub
    Ed25519PublicKey.from_public_bytes(pub).verify(base64.b64decode(cert["signature"]),
                                                   _canonical_without_signature(cert))
    assert proof_mod.verify(cert)["ok"] is True


def test_recomputed_digest_after_edit_is_rejected(signing_key):
    cert = proof_mod.mint("ev_1", _public_view(), [])
    forged = dict(cert, verdict="VERIFIED", gates=[{"gate": "GH_INTEGRITY", "result": "PASS", "reason": "forged"}])
    # The old scheme: an attacker recomputes sha256 over the edited body and puts it in `signature`.
    forged["signature"] = hashlib.sha256(_canonical_without_signature(forged)).hexdigest()
    assert proof_mod.verify(forged)["ok"] is False
    edited = dict(cert, model="other-model")
    assert proof_mod.verify(edited)["ok"] is False


def test_certificate_signed_by_another_key_is_rejected(signing_key, monkeypatch):
    cert = proof_mod.mint("ev_1", _public_view(), [])
    other = Ed25519PrivateKey.generate()
    pub_other = other.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    # Attacker edits the body, re-signs it with their own key and embeds their own public key.
    forged = dict(cert, verdict="VERIFIED", model="attacker-model")
    forged["public_key"] = base64.b64encode(pub_other).decode()
    forged["signature"] = base64.b64encode(other.sign(_canonical_without_signature(forged))).decode()
    assert proof_mod.verify(forged)["ok"] is False, "verify must trust the server key, not the key inside the cert"


def test_public_key_endpoint_publishes_the_verification_key(signing_key):
    r = c.get("/v1/proof/key")
    assert r.status_code == 200, r.text
    body = r.json()
    pub = signing_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert body["algorithm"] == "Ed25519" and base64.b64decode(body["public_key"]) == pub
    assert "private" not in json.dumps(body).lower()


def test_without_a_key_certificates_say_unsigned(monkeypatch):
    monkeypatch.delenv("EVO_PROOF_SIGNING_KEY", raising=False)
    cert = proof_mod.mint("ev_1", _public_view(), [])
    assert cert["signed"] is False and cert.get("signature") in (None, "")
    assert proof_mod.verify(cert)["ok"] is False
    assert c.get("/v1/proof/key").status_code == 404


# ---- evolution budget ----

def test_evolution_worst_case_over_cap_is_refused_before_any_call(monkeypatch):
    monkeypatch.setenv("EVO_EVOLUTION_MAX_CENTS", "1500")
    from evoforge import broker_meta
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: pytest.fail("provider called"))
    before = ledger.snapshot()
    r = c.post("/v1/evolution/start", json={"goal": "g", "max_generations": 10, "population": 5})
    assert r.status_code == 402, r.text
    assert "12000" in r.text or "1500" in r.text  # the refusal names the worst case or the cap
    assert ledger.snapshot()["reserved_cents"] == before["reserved_cents"]
    assert c.get("/v1/evolution").json().get("evolutions", []) == []


def test_evolution_within_cap_starts(monkeypatch):
    monkeypatch.setenv("EVO_EVOLUTION_MAX_CENTS", "1500")
    r = c.post("/v1/evolution/start", json={"goal": "g", "max_generations": 2, "population": 2})
    assert r.status_code == 201, r.text  # 2 x 2 x 2 calls x 120c = 960c <= 1500c


def test_evolution_cap_has_a_safe_default(monkeypatch):
    monkeypatch.delenv("EVO_EVOLUTION_MAX_CENTS", raising=False)
    r = c.post("/v1/evolution/start", json={"goal": "g", "max_generations": 10, "population": 5})
    assert r.status_code == 402, "the default cap must refuse the 12000c worst case"
