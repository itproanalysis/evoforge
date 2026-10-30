"""Spec-first verifier (WVI-2610.28667): critic never sees builder transcript.

Phase A: sealed tests from goal_contract only (before diff).
Phase B: review of diff + CI using own sealed tests.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlparse

CRITIC_SYSTEM = (
    "You are EvoForge Critic (independent verifier). You NEVER see builder rationale, "
    "transcript, or self-assessment. Phase A: write acceptance tests from the SPEC only. "
    "Phase B: review the diff and CI results against your sealed tests. Sealed tests are the held-out "
    "suite: at least 3 pytest tests, each labelled kind compositional, negative or boundary (all three present). "
    "Tests may import only the Python standard library, pytest and the target modules (by file stem): the verifier "
    "has no other packages and no network. "
    'Output JSON: {"sealed_tests": [{"code": "...", "kind": "compositional|negative|boundary"}], '
    '"review": {"result": "PASS|FAIL", "findings": [...]}}'
)


ALLOWED_SEALED_KINDS = frozenset({"compositional", "negative", "boundary"})

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
DEFAULT_PROVIDER = "api.meta.ai"


def _host_of(base_url: str) -> str:
    """Host of a base URL (e.g. ``api.fireworks.ai``); default host when unparseable."""
    try:
        host = urlparse(base_url).hostname
    except Exception:
        host = None
    return host or DEFAULT_PROVIDER


def critic_endpoint() -> dict:
    """Where Critic calls go: base URL, model, provider host, second-provider flag.

    The second provider (another Meta open-weight model via Fireworks or
    Baseten) applies when CRITIC_API_BASE and CRITIC_API_KEY are both set;
    otherwise today's MODEL_API_BASE + MODEL_API_KEY. The key never appears
    in the returned dict. Read at call time.
    """
    from evoforge import collaboration
    model = os.getenv("MODEL_CRITIC", collaboration.CRITIC if collaboration.enabled() else DEFAULT_MODEL)
    second_base = os.getenv("CRITIC_API_BASE")
    second_key = os.getenv("CRITIC_API_KEY")
    if second_base and second_key:
        return {"base_url": second_base, "model": model,
                "provider": _host_of(second_base), "second": True}
    base_url = os.getenv("MODEL_API_BASE", DEFAULT_BASE_URL)
    from evoforge import platform_models
    if platform_models.is_platform_model(model) and model != DEFAULT_MODEL:
        return {"base_url": None, "model": model,
                "provider": platform_models.model_spec(model).provider, "second": False}
    return {"base_url": base_url, "model": model,
            "provider": _host_of(base_url), "second": False}


def _output_budget() -> int:
    """Output-token budget for Critic Muse Spark chat calls.

    Reasoning models spend thinking tokens from the same budget, so the
    critic default (16000) is roomier than the builder default (8000).
    Env MODEL_CRITIC_MAX_TOKENS wins, then MODEL_MAX_TOKENS, then 16000.
    Missing, non-int or <= 0 falls back to 16000. Read at call time.
    """
    try:
        raw = os.getenv("MODEL_CRITIC_MAX_TOKENS", os.getenv("MODEL_MAX_TOKENS"))
        value = int(raw) if raw is not None else 16000
    except (TypeError, ValueError):
        return 16000
    return value if value > 0 else 16000


def _is_truncated(resp) -> bool:
    try:
        choices = getattr(resp, "choices", None)
        if not choices:
            return False
        return getattr(choices[0], "finish_reason", None) == "length"
    except Exception:
        return False


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
    from evoforge import collaboration
    if collaboration.enabled():
        collaboration.require_ready()
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
    from evoforge.broker_meta import (
        ProviderNotAccepted, ProviderOutcomeUnknown, call_metadata, provider_errors,
    )
    from evoforge.performance import critic_prices

    endpoint = critic_endpoint()
    if endpoint["second"] and critic_prices() is None:
        # Refuse before creating any client: nothing sent, nothing billed.
        # The owner sets both prices from the provider's price page.
        raise ProviderNotAccepted(
            "critic provider prices not configured "
            "(set CRITIC_PRICE_INPUT_PER_MTOK and CRITIC_PRICE_OUTPUT_PER_MTOK)")
    import openai

    model = endpoint["model"]
    provider = endpoint["provider"]
    from evoforge import platform_models
    if not endpoint["second"] and model != DEFAULT_MODEL and platform_models.is_platform_model(model):
        client = platform_models.client_for(model)
    else:
        client = openai.OpenAI(base_url=endpoint["base_url"],
                           # A provider's key goes only to that provider: CRITIC_API_KEY never reaches the Meta
                           # endpoint when CRITIC_API_BASE is unset.
                           api_key=(os.environ["CRITIC_API_KEY"] if endpoint["second"]
                                    else os.environ["MODEL_API_KEY"]),
                           max_retries=0)
    completed = []

    def complete(messages, phase):
        budget = _output_budget()

        def send():
            with provider_errors():
                return client.chat.completions.create(
                    model=model, messages=messages,
                    response_format={"type": "json_object"}, max_tokens=budget)
        try:
            response = dispatch(send) if dispatch is not None else send()
        except (ProviderNotAccepted, ProviderOutcomeUnknown):
            # A standalone aggregate caller must never refund an earlier
            # successful phase when a later phase is rejected or times out.
            if completed:
                raise ProviderOutcomeUnknown("critic partially completed", completed) from None
            raise
        completed.append({**call_metadata(response, model, phase),
                          "provider": provider})
        return response, budget

    a, budget_a = complete([{"role": "system", "content": CRITIC_SYSTEM},
                  {"role": "user", "content": f"SPEC (Phase A, no diff shown):\n{goal_contract}"}], "critic_spec")
    if _is_truncated(a):
        return {"sealed_tests": [], "stub": False, "model": model, "provider": provider,
                "provider_calls": completed,
                "execution_verified": False,
                "review": {"result": "INCONCLUSIVE", "findings": [
                    {"note": f"truncated Phase A output (finish_reason='length', budget {budget_a})",
                     "evidence": "none"}]}}
    sealed = _json(a).get("sealed_tests", [])
    ok, _normalized, shape_findings = ensure_sealed_suite(sealed)
    if not ok:
        return {"sealed_tests": [], "stub": False, "model": model, "provider": provider,
                "provider_calls": completed,
                "execution_verified": False,
                "review": {"result": "INCONCLUSIVE", "findings": shape_findings or [
                    {"note": "invalid sealed suite", "evidence": "none"}]}}
    b, budget_b = complete([{"role": "system", "content": CRITIC_SYSTEM},
                  {"role": "user", "content": f"SPEC:\n{goal_contract}\nDIFF:\n{diff}\nCI:\n{ci}\nSEALED:\n{json.dumps(sealed)}"}], "critic_review")
    if _is_truncated(b):
        return {"review": {"result": "INCONCLUSIVE", "findings": [
                    {"note": f"truncated Phase B output (finish_reason='length', budget {budget_b})",
                     "evidence": "none"}]},
                "sealed_tests": sealed, "stub": False, "model": model, "provider": provider,
                "provider_calls": completed, "execution_verified": False}
    data = _json(b)
    review = data.get("review")
    if (not isinstance(review, dict) or review.get("result") not in {"PASS", "FAIL", "INCONCLUSIVE"}
            or not isinstance(review.get("findings", []), list)):
        data["review"] = {"result": "INCONCLUSIVE", "findings": [{"note": "unparseable critic output", "evidence": "none"}]}
    return {"review": data["review"], "sealed_tests": sealed, "stub": False, "model": model,
            "provider": provider, "provider_calls": completed, "execution_verified": False}
