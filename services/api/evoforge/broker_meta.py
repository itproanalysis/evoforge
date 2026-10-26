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


@contextmanager
def provider_errors():
    """Map official SDK errors onto the two reservation outcomes (p.09 call path)."""
    import openai

    try:
        yield
    except (openai.AuthenticationError, openai.PermissionDeniedError, openai.BadRequestError,
            openai.NotFoundError, openai.UnprocessableEntityError, openai.RateLimitError) as e:
        raise ProviderNotAccepted(f"{type(e).__name__}: {e}") from e
    except openai.APIError as e:  # timeout, connection drop, 5xx, other status
        raise ProviderOutcomeUnknown(f"{type(e).__name__}: {e}") from e


def _client():
    from openai import OpenAI

    return OpenAI(
        base_url=os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1"),
        api_key=os.environ["MODEL_API_KEY"],
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


def call_critic(goal: str, diff: str) -> dict:
    """Spec-first critic via Muse Spark. Stub without key (deterministic)."""
    from evoforge.critic import call_critic as _c

    return _c(goal, diff)


def call_builder(goal: str, repo_sha: str) -> dict:
    """Call Muse Spark builder. Raises RuntimeError without key (fail-closed)."""
    if not os.getenv("MODEL_API_KEY"):
        # Deterministic stub so UI/evals work without billing; NEVER claim as model output.
        return {
            "diff": ("--- /dev/null\n+++ b/evoforge_goal.txt\n@@ -0,0 +1,2 @@\n"
                     f"+goal: {' '.join(goal.split())}\n+base: {repo_sha}\n"),  # valid new-file diff
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
    data["stub"] = False
    data["model"] = model
    data["usage"] = getattr(resp, "usage", None).model_dump() if getattr(resp, "usage", None) else {}
    return data
