"""Critic acceptance (sealed during build, promoted after) — T32: a verified PR carries its proof — signed certificate summary and a public /verify link —
so a reviewer can check the result without trusting EvoForge's word (roadmap M3)."""
from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import github  # noqa: E402
from evoforge import proof as proof_mod  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
WEB = "https://web.example.test"
DIFF = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def mul(a, b):\n-    return a + b\n+    return a * b\n"


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_create_pr(diff, title, body, branch, base="main", client=None, **kw):
        seen.update(diff=diff, title=title, body=body)
        return {"html_url": "https://github.com/o/r/pull/99", "number": 99}

    monkeypatch.setattr(github, "create_pr", fake_create_pr)
    monkeypatch.setenv("EVO_PUBLIC_WEB_URL", WEB)
    return seen


def _verified_run_evidence():
    return main._store_evidence({
        "diff": DIFF,
        "gates": [{"gate": "GH_INTEGRITY", "result": "PASS", "reason": "ok"},
                  {"gate": "GC_COMPOSITION", "result": "PASS", "reason": "ok"},
                  {"gate": "G2_REQUIRED", "result": "PASS", "reason": "visible 3/3, held-out 4/4"}],
        "run": {"base": "a" * 40, "visible": {"n": 3, "pass": 3}, "heldout": {"n": 4, "pass": 4}},
        "tests": [],
    })


def _signing_key(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", base64.b64encode(raw).decode())
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(pub).decode()


def test_signed_pr_body_carries_verify_link_signature_and_key(captured, monkeypatch):
    pub_b64 = _signing_key(monkeypatch)
    eid = _verified_run_evidence()
    r = c.post("/v1/pr/create", json={"evidence_id": eid, "title": "fix mul"})
    assert r.status_code == 200, r.text
    body = captured["body"]
    assert f"{WEB}/verify/{eid}" in body, body
    assert "Ed25519" in body
    assert pub_b64[:16] in body, "the public key fingerprint must be in the PR body"
    sig = re.search(r"[Ss]ignature[^A-Za-z0-9+/=]*([A-Za-z0-9+/=]{80,})", body)
    assert sig, body
    cert = c.get(f"/v1/proof/{eid}").json()
    assert cert["signed"] is True and cert["verify"]["ok"] is True
    assert proof_mod.verify({k: v for k, v in cert.items() if k != "verify"})["ok"] is True


def test_pr_evidence_records_the_certificate(captured, monkeypatch):
    _signing_key(monkeypatch)
    eid = _verified_run_evidence()
    r = c.post("/v1/pr/create", json={"evidence_id": eid, "title": "fix mul"})
    pr_eid = r.json()["evidence_id"]
    stored = c.get(f"/v1/evidence/{pr_eid}").json()
    blob = str(stored)
    assert "cert_" in blob and "Ed25519" in blob, stored


def test_unsigned_pr_body_says_so_and_never_shows_a_fake_signature(captured, monkeypatch):
    monkeypatch.delenv("EVO_PROOF_SIGNING_KEY", raising=False)
    eid = _verified_run_evidence()
    r = c.post("/v1/pr/create", json={"evidence_id": eid, "title": "fix mul"})
    assert r.status_code == 200, r.text
    body = captured["body"]
    assert re.search(r"[Uu]nsigned", body), body
    assert not re.search(r"[A-Za-z0-9+/=]{80,}", body), "no signature-looking blob when unsigned"
    assert f"{WEB}/verify/{eid}" in body


def test_blocked_gates_still_open_no_pr(captured, monkeypatch):
    _signing_key(monkeypatch)
    eid = main._store_evidence({"diff": DIFF, "gates": [{"gate": "GH_INTEGRITY", "result": "INCONCLUSIVE", "reason": "x"}],
                                "run": {"base": "a" * 40}, "tests": []})
    r = c.post("/v1/pr/create", json={"evidence_id": eid, "title": "x"})
    assert r.status_code == 409 and "body" not in captured
