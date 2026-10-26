"""Meta Model API broker — official SDK only, platform key (D-019).

Base URL: https://api.meta.ai/v1, Bearer MODEL_API_KEY.
OpenAI-compatible surface; no LiteLLM gateway (D-017).
"""
from __future__ import annotations

import os


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


def call_builder(goal: str, repo_sha: str) -> dict:
    """Call Muse Spark builder. Raises RuntimeError without key (fail-closed)."""
    if not os.getenv("MODEL_API_KEY"):
        # Deterministic stub so UI/evals work without billing; NEVER claim as model output.
        return {
            "diff": f"--- a/goal.txt\n+++ b/goal.txt\n@@\n+goal: {goal}\n+base: {repo_sha}\n",
            "tests": [{"code": "assert True  # stub — replace with Muse Spark output"}],
            "rationale": "stub (no MODEL_API_KEY)",
            "stub": True,
        }
    client = _client()
    model = os.getenv("MODEL_BUILDER", "muse-spark-1.3")
    resp = client.chat.completions.create(
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
        data = {"diff": "", "tests": [], "rationale": "unparseable model output"}
    data["stub"] = False
    data["model"] = model
    data["usage"] = getattr(resp, "usage", None).model_dump() if getattr(resp, "usage", None) else {}
    return data
