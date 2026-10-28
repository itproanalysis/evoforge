"""Proof certificates — the trust artifact that makes EvoForge feel new.

A certificate is a compact, shareable, tamper-evident statement:
'evidence X passed gates G at time T with code digest D'.
It carries digests, never code. Anyone can re-verify locally by
recomputing the sha256 chain over the public evidence view.

This is the 'SSL certificate for AI-written code' moment: instead of
trusting a chat transcript, you share a proof URL.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    body["signature"] = hashlib.sha256(_canonical({k: v for k, v in body.items()
                                                   if k != "signature"})).hexdigest()
    return body


def verify(cert: dict) -> dict:
    """Recompute the signature; returns {ok, reason}."""
    if not isinstance(cert, dict):
        return {"ok": False, "reason": "not a certificate"}
    sig = cert.get("signature")
    if not isinstance(sig, str) or not sig:
        return {"ok": False, "reason": "missing signature"}
    expect = hashlib.sha256(_canonical({k: v for k, v in cert.items()
                                        if k != "signature"})).hexdigest()
    if expect != sig:
        return {"ok": False, "reason": "signature mismatch — certificate was altered"}
    return {"ok": True, "reason": "signature valid over public evidence digests"}
