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
    "\nTest rules:"
    "\n- Every test is a top-level `def test_*():` function with runnable Python code, never prose."
    "\n- Assert concrete expected values with `==` (e.g. `assert calc.div(6, 3) == 2`)."
    "\n- Expected exceptions use `import pytest` and `with pytest.raises(ValueError):` around the call."
    "\n- Never write `assert True`, `assert False`, or try/except around the code under test."
    "\n- Never assert only truthy or not None when a concrete value is known."
)


CRITIC_SYSTEM = (
    "You are EvoForge Critic (independent verifier). You NEVER see builder rationale. "
    "Write acceptance tests from the SPEC only, then review diff+CI. "
    'Output JSON: {"sealed_tests": [{"code": "..."}], "review": {...}}'
    "\nTest rules:"
    "\n- Every test is a top-level `def test_*():` function with runnable Python code, never prose."
    "\n- Assert concrete expected values with `==` (e.g. `assert calc.div(6, 3) == 2`)."
    "\n- Expected exceptions use `import pytest` and `with pytest.raises(ValueError):` around the call."
    "\n- Never write `assert True`, `assert False`, or try/except around the code under test."
    "\n- Never assert only truthy or not None when a concrete value is known."
)


def call_critic(goal: str, diff: str, ci: str = "", *, dispatch=None) -> dict:
    """Spec-first critic via Muse Spark. Stub without key (deterministic)."""
    from evoforge.critic import call_critic as _c

    return _c(goal, diff, ci, dispatch=dispatch)


def _output_budget() -> int:
    """Single output-token budget for every Muse Spark chat call.

    From env MODEL_MAX_TOKENS (default 8000); missing, non-int or <= 0
    falls back to 8000. Read at call time.
    """
    try:
        raw = os.getenv("MODEL_MAX_TOKENS")
        value = int(raw) if raw is not None else 8000
    except (TypeError, ValueError):
        return 8000
    return value if value > 0 else 8000


def _is_truncated(resp) -> bool:
    try:
        choices = getattr(resp, "choices", None)
        if not choices:
            return False
        return getattr(choices[0], "finish_reason", None) == "length"
    except Exception:
        return False


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


def call_builder(goal: str, repo_sha: str, file_context: list[dict] | None = None) -> dict:
    """Call Muse Spark; without a key return an explicitly marked demo candidate."""
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
    budget = _output_budget()
    user_content = f"Goal: {goal}\nBase SHA: {repo_sha}"
    if file_context:
        blocks: list[str] = []
        for entry in file_context:
            if not isinstance(entry, dict):
                continue
            p = entry.get("path", "")
            if not isinstance(p, str):
                p = str(p)
            if "skipped" in entry:
                blocks.append(f"```\n# path: {p}\n[skipped: {entry['skipped']}]\n```")
            elif isinstance(entry.get("content"), str):
                content = entry["content"]
                raw = content.encode("utf-8")
                if len(raw) > 32 * 1024:
                    cut = raw[:32 * 1024].decode("utf-8", errors="ignore")
                    content = cut + "\n... [truncated]"
                blocks.append(f"```\n# path: {p}\n{content}\n```")
        if blocks:
            user_content = (user_content + "\n\nFile context (target files at base):\n"
                            + "\n".join(blocks))
    with provider_errors():
        resp = _client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": BUILDER_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            max_tokens=budget,
        )
    import json

    if _is_truncated(resp):
        data = {"diff": "", "tests": [],
                "rationale": f"truncated model output (finish_reason='length', budget {budget})"}
    else:
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
