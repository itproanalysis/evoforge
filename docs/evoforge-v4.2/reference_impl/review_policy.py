"""Verifier independence + review signal rules (EvoForge v4.1, executable spec).

Adopted:
  * arXiv:2610.28667 (Who Verifies the Builder, ADOPT): what made verification work was context
    independence and writing acceptance tests from the spec BEFORE reading the builder's code; a
    verifier from a different provider was not better on its own. v4.0's "different model family"
    rule for HIGH_RISK is replaced by: qualified + context-independent + spec-first, and feedback
    to the builder is counterexamples only (no rationale leakage in either direction).
  * arXiv:2603.11078 (CR-Bench, ADOPT): reviewer precision is low and self-reflection raises recall
    at the cost of noise, so a BLOCKING finding must carry executable evidence; findings without it
    are downgraded to advisory and capped per candidate.
"""
from __future__ import annotations

import json
import os

_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "quality_gates.json")


def _cfg() -> dict:
    with open(_GATES, encoding="utf-8") as fh:
        return json.load(fh)


def check_independence(risk: str, verifier: dict, cfg: dict | None = None) -> tuple[bool, list[str]]:
    """verifier = {qualified: bool, inputs: [..], spec_tests_sealed_at: iso|None, diff_first_read_at: iso|None,
                   feedback: [{kind, ...}]}"""
    c = (cfg or _cfg())["independence"]
    if risk not in c["applies_to"]:
        return True, []
    bad = []
    if c["verifier_must_be_qualified"] and not verifier.get("qualified"):
        bad.append("verifier not qualified for this risk level")
    leaked = sorted(set(verifier.get("inputs", [])) & set(c["verifier_forbidden_inputs"]))
    if leaked:
        bad.append(f"context not independent: saw {leaked}")
    unknown = sorted(set(verifier.get("inputs", [])) - set(c["verifier_allowed_inputs"]) - set(c["verifier_forbidden_inputs"]))
    if unknown:
        bad.append(f"inputs outside allow-list: {unknown}")
    sealed, read = verifier.get("spec_tests_sealed_at"), verifier.get("diff_first_read_at")
    if not sealed:
        bad.append("phase A missing: no spec-first acceptance tests sealed")
    elif read and read <= sealed:
        bad.append("phase order violated: diff read before spec tests were sealed")
    for fb in verifier.get("feedback", []):
        if fb.get("kind") != "counterexample" or any(not fb.get(k) for k in c["counterexample_fields"]):
            bad.append("feedback to builder must be a complete counterexample")
            break
    return not bad, bad


def triage_findings(findings: list[dict], cfg: dict | None = None) -> dict:
    """findings: [{id, severity, blocking: bool, evidence: {kind, ref}|None}] -> blocking / advisory split."""
    c = (cfg or _cfg())["review_signal"]
    blocking, advisory = [], []
    for f in findings:
        ev = f.get("evidence") or {}
        if f.get("blocking") and ev.get("kind") in c["accepted_evidence"] and ev.get("ref"):
            blocking.append(f)
        else:
            advisory.append(dict(f, blocking=False, downgraded=bool(f.get("blocking"))))
    advisory.sort(key=lambda f: ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(f.get("severity"), 4), f["id"]))
    shown = advisory[: c["max_advisory_comments_per_candidate"]]
    return {"blocking": blocking, "advisory": shown, "suppressed": len(advisory) - len(shown),
            "merge_blocked": bool(blocking)}
