"""T33: proof certificates are issued once, stored, and fetchable by id."""
from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path

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


def _signing_key(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", base64.b64encode(raw).decode())
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(pub).decode()


def _verified_run_evidence():
    return main._store_evidence({
        "diff": DIFF,
        "gates": [{"gate": "GH_INTEGRITY", "result": "PASS", "reason": "ok"},
                  {"gate": "GC_COMPOSITION", "result": "PASS", "reason": "ok"},
                  {"gate": "G2_REQUIRED", "result": "PASS", "reason": "visible 3/3, held-out 4/4"}],
        "run": {"base": "a" * 40, "visible": {"n": 3, "pass": 3}, "heldout": {"n": 4, "pass": 4}},
        "tests": [],
    })


def test_proof_is_stable_across_reads(monkeypatch):
    _signing_key(monkeypatch)
    eid = _verified_run_evidence()
    first = c.get(f"/v1/proof/{eid}").json()
    second = c.get(f"/v1/proof/{eid}").json()
    assert first["certificate_id"] == second["certificate_id"]
    assert first["issued_at"] == second["issued_at"]
    assert first["signature"] == second["signature"]
    assert first["verify"]["ok"] is True and second["verify"]["ok"] is True
    # The stored body is exactly the signed body: no "verify" envelope inside.
    stored = main._evidence[main._proof_evidence_key(eid)]["certificate"]
    assert "verify" not in stored
    assert stored["certificate_id"] == first["certificate_id"]
    assert stored["signature"] == first["signature"]


def test_proof_cert_by_id_roundtrips_and_verifies_offline(monkeypatch):
    _signing_key(monkeypatch)
    eid = _verified_run_evidence()
    cert = c.get(f"/v1/proof/{eid}").json()
    cid = cert["certificate_id"]
    fetched = c.get(f"/v1/proof/cert/{cid}").json()
    assert fetched["certificate_id"] == cid
    assert fetched["signature"] == cert["signature"]
    assert fetched["issued_at"] == cert["issued_at"]
    assert fetched["verify"]["ok"] is True
    # Offline check with the published key: strip the envelope, verify the body.
    key = c.get("/v1/proof/key").json()
    assert key["public_key"] == fetched["public_key"]
    body = {k: v for k, v in fetched.items() if k != "verify"}
    assert proof_mod.verify(body)["ok"] is True
    assert c.get("/v1/proof/cert/cert_doesnotexist000").status_code == 404


def test_pr_body_quotes_the_stored_certificate(monkeypatch):
    _signing_key(monkeypatch)
    seen = {}

    def fake_create_pr(diff, title, body, branch, base="main", client=None, **kw):
        seen.update(diff=diff, title=title, body=body)
        return {"html_url": "https://github.com/o/r/pull/99", "number": 99}

    monkeypatch.setattr(github, "create_pr", fake_create_pr)
    monkeypatch.setenv("EVO_PUBLIC_WEB_URL", WEB)
    eid = _verified_run_evidence()
    r = c.post("/v1/pr/create", json={"evidence_id": eid, "title": "fix mul"})
    assert r.status_code == 200, r.text
    body = seen["body"]
    cert = c.get(f"/v1/proof/{eid}").json()
    assert cert["certificate_id"] in body
    assert cert["signature"] in body
    by_id = c.get(f"/v1/proof/cert/{cert['certificate_id']}").json()
    assert by_id["signature"] == cert["signature"]
    m = re.search(r"Proof certificate:\s+(cert_[A-Za-z0-9]+)", body)
    assert m and m.group(1) == cert["certificate_id"]
