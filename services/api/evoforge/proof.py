"""Proof certificates — the trust artifact that makes EvoForge feel new.

A certificate is a compact, shareable, tamper-evident statement:
'evidence X passed gates G at time T with code digest D'.
It carries digests, never code.

When EVO_PROOF_SIGNING_KEY is configured, the certificate is signed with
Ed25519 and anyone holding the server's public key (GET /v1/proof/key) can
verify that the certificate bytes were minted by this server and have not
been edited since: any change to a body field invalidates the signature,
and the signature cannot be recomputed without the private key. This is
the 'SSL certificate for AI-written code' moment: instead of trusting a
chat transcript, you share a proof URL.

What is NOT proven: the signature says nothing about whether the gates
themselves are sufficient, whether the underlying code is correct or
safe, or who ran the model — it proves provenance and integrity of the
certificate bytes (this server minted these exact fields), not the truth
of the wider world beyond the digests carried inside.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import time
import uuid

_SIGNED_EXCLUDE = frozenset({"signature", "public_key", "algorithm", "signed"})
# "verify" is response-envelope metadata added by the HTTP layer, never part
# of the signed body, so it must not affect verification either.
_VERIFY_EXCLUDE = frozenset({"signature", "public_key", "algorithm", "signed", "verify"})


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_private_key():
    """Raw Ed25519 private key from EVO_PROOF_SIGNING_KEY, or None.

    The env value is base64 of the 32-byte raw private key. Never logged
    or returned. Any missing/invalid value means 'no key configured'.
    """
    raw_b64 = os.getenv("EVO_PROOF_SIGNING_KEY", "").strip()
    if not raw_b64:
        return None
    try:
        raw = base64.b64decode(raw_b64, validate=True)
    except Exception:
        return None
    if len(raw) != 32:
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        return Ed25519PrivateKey.from_private_bytes(raw)
    except Exception:
        return None


def server_public_key_b64() -> str | None:
    """Base64 raw 32-byte server public key, or None when unconfigured."""
    priv = _load_private_key()
    if priv is None:
        return None
    try:
        from cryptography.hazmat.primitives import serialization

        pub_raw = priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return base64.b64encode(pub_raw).decode("ascii")
    except Exception:
        return None


def mint(evidence_id: str, public_evidence: dict, chain: list[dict]) -> dict:
    """Mint a certificate over an already-redacted public evidence view."""
    gates = public_evidence.get("gates") if isinstance(public_evidence.get("gates"), list) else []
    verdicts = [{"gate": g.get("gate"), "result": g.get("result"),
                 "reason": g.get("reason", "")} for g in gates if isinstance(g, dict)]
    all_pass = bool(verdicts) and all(v["result"] == "PASS" for v in verdicts)
    body = {
        "certificate_id": f"cert_{uuid.uuid4().hex[:12]}",
        "evidence_id": evidence_id,
        "issued_at": time.time(),
        "verdict": "VERIFIED" if all_pass else "NOT_VERIFIED",
        "gates": verdicts,
        "chain": [{"stage": c.get("stage"), "event_id": c.get("event_id")} for c in chain],
        "diff_sha256": public_evidence.get("diff_sha256", ""),
        "sealed_kinds": public_evidence.get("sealed_kinds", []),
        "sealed_count": public_evidence.get("sealed_count", 0),
        "model": public_evidence.get("model", ""),
    }
    priv = _load_private_key()
    if priv is None:
        # Honest unsigned certificate: never a digest pretending to be a signature.
        body["algorithm"] = None
        body["signed"] = False
        body["public_key"] = None
        body["signature"] = None
        return body
    try:
        from cryptography.hazmat.primitives import serialization

        pub_raw = priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        sig = priv.sign(_canonical({k: v for k, v in body.items()
                                   if k not in _SIGNED_EXCLUDE}))
        body["algorithm"] = "Ed25519"
        body["signed"] = True
        body["public_key"] = base64.b64encode(pub_raw).decode("ascii")
        body["signature"] = base64.b64encode(sig).decode("ascii")
        return body
    except Exception:
        body["algorithm"] = None
        body["signed"] = False
        body["public_key"] = None
        body["signature"] = None
        return body


_ARENA_MANIFEST_KEYS = (
    "task_spec_hash",
    "heldout_hash",
    "base_tree_sha",
    "prompt_hash",
    "acceptance_hash",
    "acceptance_count",
    "acceptance_inherited",
    "acceptance_new",
    "acceptance_dropped",
    "heldout_count",
    "comparison_mode",
    "cost_basis",
    "runner_cost",
    "suite_version",
    "task_id",
    "disclosure",
    "judge",
    "lanes",
)


def _lane_arena_summary(lane) -> dict:
    if not isinstance(lane, dict):
        lane = {}
    held = lane.get("heldout") if isinstance(lane.get("heldout"), dict) else {}
    try:
        passed = int(held.get("passed", 0))
    except (TypeError, ValueError):
        passed = 0
    try:
        n = int(held.get("n", 0))
    except (TypeError, ValueError):
        n = 0
    diff = lane.get("diff")
    if isinstance(diff, str) and diff:
        diff_sha256 = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    else:
        diff_sha256 = ""
    preview = lane.get("preview_html")
    if isinstance(preview, str) and preview:
        preview_sha256 = hashlib.sha256(preview.encode("utf-8")).hexdigest()
    else:
        preview_sha256 = ""
    try:
        cost_cents = int(lane.get("cost_cents", 0))
    except (TypeError, ValueError):
        cost_cents = 0
    try:
        attempts = int(lane.get("attempts", 0))
    except (TypeError, ValueError):
        attempts = 0
    status = lane.get("status", "")
    outcome = lane.get("outcome", "")
    return {
        "status": status if isinstance(status, str) else "",
        "outcome": outcome if isinstance(outcome, str) else "",
        "heldout": {"passed": passed, "n": n},
        "cost_cents": cost_cents,
        "attempts": attempts,
        "diff_sha256": diff_sha256,
        "preview_sha256": preview_sha256,
    }


def mint_arena(arena_doc: dict) -> dict:
    """Mint a certificate over a finished arena document (digests, never code)."""
    if not isinstance(arena_doc, dict):
        arena_doc = {}
    arena_id = arena_doc.get("arena_id", "")
    if not isinstance(arena_id, str):
        arena_id = ""
    mode = arena_doc.get("mode")
    mode = "prompt" if mode == "prompt" else "sealed"
    verdict_obj = arena_doc.get("verdict")
    if isinstance(verdict_obj, dict):
        winner = verdict_obj.get("winner", "")
    elif isinstance(verdict_obj, str):
        winner = verdict_obj
    else:
        winner = ""
    if not isinstance(winner, str):
        winner = ""
    model = arena_doc.get("model", "")
    if not isinstance(model, str):
        model = ""
    manifest_src = arena_doc.get("manifest")
    if not isinstance(manifest_src, dict):
        manifest_src = {}
    manifest = {}
    for key in _ARENA_MANIFEST_KEYS:
        if key in manifest_src:
            try:
                manifest[key] = copy.deepcopy(manifest_src[key])
            except Exception:
                manifest[key] = manifest_src[key]
    lanes_src = arena_doc.get("lanes")
    if not isinstance(lanes_src, dict):
        lanes_src = {}
    lanes = {
        "single": _lane_arena_summary(lanes_src.get("single")),
        "evoforge": _lane_arena_summary(lanes_src.get("evoforge")),
    }
    body: dict = {
        "certificate_id": f"cert_{uuid.uuid4().hex[:12]}",
        "kind": "arena",
        "arena_id": arena_id,
        "issued_at": time.time(),
        "mode": mode,
        "verdict": winner,
        "model": model,
        "manifest": manifest,
        "lanes": lanes,
    }
    if isinstance(arena_doc.get("root_id"), str) and arena_doc.get("root_id"):
        body["root_id"] = arena_doc["root_id"]
    round_index = arena_doc.get("round_index")
    if isinstance(round_index, int) and not isinstance(round_index, bool):
        body["round_index"] = round_index
    priv = _load_private_key()
    if priv is None:
        body["algorithm"] = None
        body["signed"] = False
        body["public_key"] = None
        body["signature"] = None
        return body
    try:
        from cryptography.hazmat.primitives import serialization

        pub_raw = priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        sig = priv.sign(_canonical({k: v for k, v in body.items()
                                   if k not in _SIGNED_EXCLUDE}))
        body["algorithm"] = "Ed25519"
        body["signed"] = True
        body["public_key"] = base64.b64encode(pub_raw).decode("ascii")
        body["signature"] = base64.b64encode(sig).decode("ascii")
        return body
    except Exception:
        body["algorithm"] = None
        body["signed"] = False
        body["public_key"] = None
        body["signature"] = None
        return body


def verify(cert: dict) -> dict:
    """Verify a certificate against the SERVER's configured public key.

    Returns {ok, reason}. The signature is checked with the key derived
    from EVO_PROOF_SIGNING_KEY — the key embedded in the cert is never
    used for crypto, but it must name the server's key: a cert carrying
    another key (even with an otherwise-valid signature) is rejected.
    Unsigned certs, missing keys, wrong keys, and any edited field fail.
    """
    if not isinstance(cert, dict):
        return {"ok": False, "reason": "not a certificate"}
    if cert.get("signed") is not True:
        return {"ok": False, "reason": "certificate is not signed"}
    if cert.get("algorithm") != "Ed25519":
        return {"ok": False, "reason": "unknown signature algorithm"}
    sig_b64 = cert.get("signature")
    if not isinstance(sig_b64, str) or not sig_b64:
        return {"ok": False, "reason": "missing signature"}
    priv = _load_private_key()
    if priv is None:
        return {"ok": False, "reason": "proof signing not configured"}
    try:
        import hmac as _hmac

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        server_pub_raw = priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        server_pub_b64 = base64.b64encode(server_pub_raw).decode("ascii")
        embedded = cert.get("public_key")
        if not isinstance(embedded, str) or not embedded:
            return {"ok": False, "reason": "missing public key"}
        if not _hmac.compare_digest(embedded, server_pub_b64):
            return {"ok": False,
                    "reason": "certificate was not signed by this server (wrong key)"}
        server_pub = Ed25519PublicKey.from_public_bytes(server_pub_raw)
        sig = base64.b64decode(sig_b64, validate=True)
        payload = _canonical({k: v for k, v in cert.items()
                              if k not in _VERIFY_EXCLUDE})
        server_pub.verify(sig, payload)
    except Exception:
        return {"ok": False, "reason": "signature mismatch — certificate was altered"}
    return {"ok": True, "reason": "Ed25519 signature valid over certificate body"}
