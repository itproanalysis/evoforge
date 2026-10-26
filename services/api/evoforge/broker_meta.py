"""Meta Model API broker — official SDK only, platform key (D-019).

Base URL: https://api.meta.ai/v1, Bearer MODEL_API_KEY.
OpenAI-compatible surface; no LiteLLM gateway (D-017).
"""
from __future__ import annotations

import os
from contextlib import contextmanager


class ProviderNotAccepted(Exception):
    """The provider certainly did not accept (or bill) the request -> refund."""


class ProviderOutcomeUnknown(Exception):
    """The request may have been accepted -> keep the reservation for reconciliation."""

    def __init__(self, message: str, completed_calls: list[dict] | None = None):
        super().__init__(message)
        self.completed_calls = tuple(completed_calls or [])


@contextmanager
def provider_errors():
    """Map official SDK errors onto the two reservation outcomes (p.09 call path)."""
    import openai

    try:
        yield
    except (openai.AuthenticationError, openai.PermissionDeniedError, openai.BadRequestError,
            openai.NotFoundError, openai.UnprocessableEntityError, openai.RateLimitError) as e:
        raise ProviderNotAccepted(type(e).__name__) from None
    except openai.APIError as e:  # timeout, connection drop, 5xx, other status
        raise ProviderOutcomeUnknown(type(e).__name__) from None


def _client():
    from openai import OpenAI

    return OpenAI(
        base_url=os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1"),
        api_key=os.environ["MODEL_API_KEY"],
        max_retries=0,  # retries require a new reservation and outcome reconciliation
    )


BUILDER_SYSTEM = (
    "You are EvoForge Builder (seat 0). Propose ONE minimal patch as unified diff "
    "plus NEW tests only. Do not claim verification. Output JSON: "
    '{"diff": "...", "tests": [{"code": "..."}], "rationale": "..."}'
)


CRITIC_SYSTEM = (
    "You are EvoForge Critic (independent verifier). You NEVER see builder rationale. "
    "Write acceptance tests from the SPEC only, then review diff+CI. "
    'Output JSON: {"sealed_tests": [{"code": "..."}], "review": {...}}'
)


def call_critic(goal: str, diff: str, ci: str = "", *, dispatch=None) -> dict:
    """Spec-first critic via Muse Spark. Stub without key (deterministic)."""
    from evoforge.critic import call_critic as _c

    return _c(goal, diff, ci, dispatch=dispatch)


def call_metadata(response, model: str, phase: str) -> dict:
    """Transport/model metadata for later receipts; never supplied by model JSON.

    This is not a billed receipt: no currency amount or pricing is inferred.
    Completion IDs remain distinct from the transport's request ID.
    """
    usage = getattr(response, "usage", None)
    return {
        "provider": "meta", "model": model, "phase": phase,
        "provider_request_id": getattr(response, "_request_id", None),
        "provider_response_id": getattr(response, "id", None),
        "usage": usage.model_dump() if usage is not None else {},
        "billing_verified": False,
    }


def call_builder(goal: str, repo_sha: str) -> dict:
    """Call Muse Spark; without a key return an explicitly marked demo candidate."""
    if not os.getenv("MODEL_API_KEY"):
        # Deterministic stub so UI/evals work without billing; NEVER claim as model output.
        return {
            "diff": f"--- a/goal.txt\n+++ b/goal.txt\n@@\n+goal: {goal}\n+base: {repo_sha}\n",
            "tests": [{"code": "assert True  # stub — replace with Muse Spark output"}],
            "rationale": "stub (no MODEL_API_KEY)",
            "stub": True,
        }
    model = os.getenv("MODEL_BUILDER", "muse-spark-1.3")
    with provider_errors():
        resp = _client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": BUILDER_SYSTEM},
                {"role": "user", "content": f"Goal: {goal}\nBase SHA: {repo_sha}"},
            ],
            response_format={"type": "json_object"},
            max_tokens=2000,
        )
    import json

    try:
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        data = None
    if not isinstance(data, dict):  # billed but unusable: empty candidate, gates will block
        data = {"diff": "", "tests": [], "rationale": "unparseable model output"}
    tests = data.get("tests", [])
    if not isinstance(tests, list) or any(
        not isinstance(test, dict) or not isinstance(test.get("code"), str) for test in tests
    ):
        tests = []
    data = {
        "diff": data.get("diff") if isinstance(data.get("diff"), str) else "",
        "tests": tests,
        "rationale": data.get("rationale") if isinstance(data.get("rationale"), str) else "unusable model fields",
    }
    data["stub"] = False
    data["model"] = model
    data["usage"] = getattr(resp, "usage", None).model_dump() if getattr(resp, "usage", None) else {}
    data["provider_calls"] = [call_metadata(resp, model, "builder")]
    return data
