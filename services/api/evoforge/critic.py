"""Spec-first verifier (WVI-2610.28667): critic never sees builder transcript.

Phase A: sealed tests from goal_contract only (before diff).
Phase B: review of diff + CI using own sealed tests.
"""
from __future__ import annotations

import json
import os

CRITIC_SYSTEM = (
    "You are EvoForge Critic (independent verifier). You NEVER see builder rationale, "
    "transcript, or self-assessment. Phase A: write acceptance tests from the SPEC only. "
    "Phase B: review the diff and CI results against your sealed tests. Sealed tests are the held-out "
    "suite: at least 3 pytest tests, each labelled kind compositional, negative or boundary (all three present). "
    'Output JSON: {"sealed_tests": [{"code": "...", "kind": "compositional|negative|boundary"}], '
    '"review": {"result": "PASS|FAIL", "findings": [...]}}'
)


ALLOWED_SEALED_KINDS = frozenset({"compositional", "negative", "boundary"})


def ensure_sealed_suite(sealed):
    """Validate the held-out (sealed) suite shape.

    Returns (ok, normalized, findings) where normalized is the valid-entry
    subset (entries kept as given) and findings is a list of
    {note, evidence} dicts.
    """
    if not isinstance(sealed, list):
        return False, [], [{"note": "invalid sealed suite: sealed_tests must be a list", "evidence": "none"}]
    normalized = []
    findings = []
    for idx, test in enumerate(sealed):
        if not isinstance(test, dict):
            findings.append({"note": f"invalid sealed suite: entry {idx} must be an object", "evidence": "none"})
            continue
        code = test.get("code")
        kind = test.get("kind")
        if not isinstance(code, str) or not code.strip() or "def test_" not in code:
            findings.append({"note": f"invalid sealed suite: entry {idx} code must be a non-empty str containing 'def test_'",
                             "evidence": "none"})
            continue
        if kind not in ALLOWED_SEALED_KINDS:
            findings.append({"note": f"invalid sealed suite: entry {idx} kind must be one of compositional, negative, boundary",
                             "evidence": "none"})
            continue
        normalized.append(test)
    kinds_present = {t.get("kind") for t in normalized}
    missing = set(ALLOWED_SEALED_KINDS) - kinds_present
    if len(sealed) < 3:
        findings.append({"note": "invalid sealed suite: at least 3 sealed tests required", "evidence": "none"})
    if len(normalized) != len(sealed):
        findings.append({"note": "invalid sealed suite: every entry must have valid code and kind", "evidence": "none"})
    if missing:
        findings.append({"note": f"invalid sealed suite: missing kinds {sorted(missing)}", "evidence": "none"})
    ok = len(sealed) >= 3 and len(normalized) == len(sealed) and not missing
    if not ok and not findings:
        findings.append({"note": "invalid sealed suite", "evidence": "none"})
    return ok, normalized, findings


def _json(resp) -> dict:
    try:
        out = json.loads(resp.choices[0].message.content or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return out if isinstance(out, dict) else {}


def call_critic(goal_contract: str, diff: str = "", ci: str = "", *, dispatch=None) -> dict:
    """Phase A input = goal_contract only; Phase B adds diff+ci. Stub without key."""
    if not os.getenv("MODEL_API_KEY"):
        spec = json.dumps(goal_contract[:60])
        sealed = [
            {"code": f"def test_compositional_goal():\n    assert {spec} != ''  # sealed stub compositional (Phase A)",
             "kind": "compositional"},
            {"code": f"def test_negative_goal():\n    assert {spec} != 'INVALID'  # sealed stub negative (Phase A)",
             "kind": "negative"},
            {"code": f"def test_boundary_goal():\n    assert len({spec}) >= 0  # sealed stub boundary (Phase A)",
             "kind": "boundary"},
        ]
        review = {"result": "INCONCLUSIVE",
                  "findings": [{"note": "stub review (no MODEL_API_KEY); diff not trusted", "evidence": "none"}]}
        if diff:
            review["findings"].append({"note": "diff present but unverified without model", "evidence": "none"})
        return {"sealed_tests": sealed, "review": review, "stub": True,
                "execution_verified": False,
                "model": os.getenv("MODEL_CRITIC", "muse-spark-1.3")}
    from openai import OpenAI

    from evoforge.broker_meta import (
        ProviderNotAccepted, ProviderOutcomeUnknown, call_metadata, provider_errors,
    )

    model = os.getenv("MODEL_CRITIC", "muse-spark-1.3")
    client = OpenAI(base_url=os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1"),
                    api_key=os.environ["MODEL_API_KEY"], max_retries=0)
    completed = []

    def complete(messages, phase):
        def send():
            with provider_errors():
                return client.chat.completions.create(
                    model=model, messages=messages,
                    response_format={"type": "json_object"}, max_tokens=1500)
        try:
            response = dispatch(send) if dispatch is not None else send()
        except (ProviderNotAccepted, ProviderOutcomeUnknown):
            # A standalone aggregate caller must never refund an earlier
            # successful phase when a later phase is rejected or times out.
            if completed:
                raise ProviderOutcomeUnknown("critic partially completed", completed) from None
            raise
        completed.append(call_metadata(response, model, phase))
        return response

    a = complete([{"role": "system", "content": CRITIC_SYSTEM},
                  {"role": "user", "content": f"SPEC (Phase A, no diff shown):\n{goal_contract}"}], "critic_spec")
    sealed = _json(a).get("sealed_tests", [])
    ok, _normalized, shape_findings = ensure_sealed_suite(sealed)
    if not ok:
        return {"sealed_tests": [], "stub": False, "model": model, "provider_calls": completed,
                "execution_verified": False,
                "review": {"result": "INCONCLUSIVE", "findings": shape_findings or [
                    {"note": "invalid sealed suite", "evidence": "none"}]}}
    b = complete([{"role": "system", "content": CRITIC_SYSTEM},
                  {"role": "user", "content": f"SPEC:\n{goal_contract}\nDIFF:\n{diff}\nCI:\n{ci}\nSEALED:\n{json.dumps(sealed)}"}], "critic_review")
    data = _json(b)
    review = data.get("review")
    if (not isinstance(review, dict) or review.get("result") not in {"PASS", "FAIL", "INCONCLUSIVE"}
            or not isinstance(review.get("findings", []), list)):
        data["review"] = {"result": "INCONCLUSIVE", "findings": [{"note": "unparseable critic output", "evidence": "none"}]}
    return {"review": data["review"], "sealed_tests": sealed, "stub": False, "model": model,
            "provider_calls": completed, "execution_verified": False}
