"""Critic acceptance (sealed during build, promoted after) — T33: a certificate is issued once per evidence and stored, so the signature quoted in a PR can be
fetched again and verified by a third party with only the published public key."""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import github  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
DIFF = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def mul(a, b):\n-    return a + b\n+    return a * b\n"
EXCLUDED = ("signature", "public_key", "algorithm", "signed", "verify")


@pytest.fixture(autouse=True)
def key(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", base64.b64encode(raw).decode())
    monkeypatch.setenv("EVO_PUBLIC_WEB_URL", "https://web.example.test")
    return priv


def _evidence():
    return main._store_evidence({
        "diff": DIFF, "tests": [],
        "gates": [{"gate": g, "result": "PASS", "reason": "ok"} for g in ("GH_INTEGRITY", "GC_COMPOSITION", "G2_REQUIRED")],
        "run": {"base": "b" * 40, "visible": {"n": 3, "pass": 3}, "heldout": {"n": 4, "pass": 4}}})


def _third_party_verify(cert: dict) -> bool:
    """Exactly what an outside reviewer does: fetch the public key, verify the signature over the canonical body."""
    pub = base64.b64decode(c.get("/v1/proof/key").json()["public_key"])
    body = {k: v for k, v in cert.items() if k not in EXCLUDED}
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(base64.b64decode(cert["signature"]), payload)
        return True
    except Exception:
        return False


def test_certificate_is_stable_per_evidence():
    eid = _evidence()
    a = c.get(f"/v1/proof/{eid}").json()
    b = c.get(f"/v1/proof/{eid}").json()
    assert a["certificate_id"] == b["certificate_id"] and a["signature"] == b["signature"]
    assert a["issued_at"] == b["issued_at"]


def test_certificate_is_retrievable_by_id_and_verifies_offline():
    eid = _evidence()
    cert = c.get(f"/v1/proof/{eid}").json()
    r = c.get(f"/v1/proof/cert/{cert['certificate_id']}")
    assert r.status_code == 200, r.text
    again = r.json()
    assert again["signature"] == cert["signature"] and again["evidence_id"] == eid
    assert _third_party_verify(again)
    tampered = dict(again, verdict="VERIFIED" if again["verdict"] != "VERIFIED" else "NOT_VERIFIED")
    assert not _third_party_verify(tampered)


def test_pr_body_quotes_the_stored_certificate(monkeypatch):
    seen = {}
    monkeypatch.setattr(github, "create_pr", lambda diff, title, body, branch, base="main", client=None, **kw:
                        seen.update(body=body) or {"html_url": "https://github.com/o/r/pull/7", "number": 7})
    eid = _evidence()
    assert c.post("/v1/pr/create", json={"evidence_id": eid, "title": "fix"}).status_code == 200
    cert = c.get(f"/v1/proof/{eid}").json()
    assert cert["certificate_id"] in seen["body"] and cert["signature"] in seen["body"]
    m = re.search(r"cert_[0-9a-f]{6,}", seen["body"])
    fetched = c.get(f"/v1/proof/cert/{m.group(0)}").json()
    assert _third_party_verify(fetched)


def test_unknown_certificate_is_404():
    assert c.get("/v1/proof/cert/cert_doesnotexist").status_code == 404


def test_proxy_allows_certificate_lookup():
    root = Path(__file__).resolve().parents[3] / "apps" / "web" / "lib"
    src = (root / "proxyPolicy.ts").read_text(encoding="utf-8")
    cases = (root / "proxyPolicy.cases.json").read_text(encoding="utf-8")
    assert '"cert"' in src or "'cert'" in src or "/v1/proof/cert" in src
    assert "/v1/proof/cert/" in cases
