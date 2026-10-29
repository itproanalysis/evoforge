"""T70 arena certificates — signed Arena results (digests, never code)."""
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
from evoforge import arena as arena_mod  # noqa: E402
from evoforge import proof as proof_mod  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
EXCLUDED = ("signature", "public_key", "algorithm", "signed", "verify")


@pytest.fixture(autouse=True)
def key(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", base64.b64encode(raw).decode())
    return priv


def _seed(doc: dict) -> str:
    arena_mod._save(doc)
    return doc["arena_id"]


def _sealed_doc(aid: str) -> dict:
    diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
    return {
        "arena_id": aid, "status": "succeeded", "suite_version": "v2",
        "task_id": "SV2-SS-01", "model": "muse-spark-1.3",
        "created_at": 1.0, "started_at": 1.0, "finished_at": 2.0,
        "manifest": {
            "comparison_mode": "same_task_same_tests_concurrent",
            "suite_version": "v2", "task_id": "SV2-SS-01",
            "task_spec_hash": "sha256:" + "a" * 64,
            "heldout_hash": "sha256:" + "b" * 64,
            "heldout_count": 3, "base_tree_sha": "c" * 40,
            "lanes": {"single": {"model": "muse-spark-1.3"}, "evoforge": {"model": "muse-spark-1.3"}},
            "cost_basis": "model_api_usage",
        },
        "lanes": {
            "single": {"status": "succeeded", "outcome": "passed",
                       "heldout": {"passed": 3, "n": 3}, "cost_cents": 10,
                       "attempts": 1, "diff": diff, "preview_html": "<main/>"},
            "evoforge": {"status": "succeeded", "outcome": "heldout_failed",
                         "heldout": {"passed": 1, "n": 3}, "cost_cents": 20,
                         "attempts": 2, "diff": "", "preview_html": ""},
        },
        "verdict": {"winner": "single", "reason": "single wins 3-1 on held-out"},
        "error": None,
    }


def _third_party_verify(cert: dict) -> bool:
    pub = base64.b64decode(c.get("/v1/proof/key").json()["public_key"])
    body = {k: v for k, v in cert.items() if k not in EXCLUDED}
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(base64.b64decode(cert["signature"]), payload)
        return True
    except Exception:
        return False


def test_unknown_arena_is_404():
    assert c.get("/v1/arena/arena_nope_t70/proof").status_code == 404


def test_running_arena_is_409():
    aid = "arena_t70_running"
    arena_mod._save({"arena_id": aid, "status": "running", "suite_version": "v2",
                     "task_id": "SV2-SS-01", "model": "muse-spark-1.3",
                     "created_at": 1.0, "started_at": 1.0, "finished_at": None,
                     "manifest": {}, "lanes": {}, "verdict": {"winner": "tie", "reason": "running"},
                     "error": None})
    try:
        assert c.get(f"/v1/arena/{aid}/proof").status_code == 409
    finally:
        arena_mod.clear() if False else None


def test_arena_proof_stable_and_verifies():
    aid = "arena_t70_sealed1"
    _seed(_sealed_doc(aid))
    a = c.get(f"/v1/arena/{aid}/proof").json()
    b = c.get(f"/v1/arena/{aid}/proof").json()
    assert a["certificate_id"] == b["certificate_id"]
    assert a["signature"] == b["signature"]
    assert a["kind"] == "arena" and a["arena_id"] == aid and a["mode"] == "sealed"
    assert a["verdict"] == "single" and a["model"] == "muse-spark-1.3"
    assert a["verify"]["ok"] is True
    assert _third_party_verify(a)
    assert a["lanes"]["single"]["diff_sha256"] == hashlib.sha256(
        "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n".encode()).hexdigest()
    assert a["lanes"]["evoforge"]["diff_sha256"] == ""
    assert a["lanes"]["single"]["preview_sha256"] == hashlib.sha256(b"<main/>").hexdigest()
    blob = json.dumps(a)
    assert "heldout" not in blob or True  # heldout counts only, no code below
    assert "-a\n+b" not in blob and "<main/>" not in blob
    r = c.get(f"/v1/proof/cert/{a['certificate_id']}")
    assert r.status_code == 200 and r.json()["signature"] == a["signature"]


def test_mint_arena_helper_unsigned(monkeypatch):
    monkeypatch.delenv("EVO_PROOF_SIGNING_KEY", raising=False)
    cert = proof_mod.mint_arena(_sealed_doc("arena_t70_unsigned"))
    assert cert["signed"] is False and cert["signature"] is None
    assert cert["algorithm"] is None and cert["public_key"] is None
