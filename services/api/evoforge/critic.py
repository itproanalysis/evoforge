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
    "Phase B: review the diff and CI results against your sealed tests. "
    'Output JSON: {"sealed_tests": [{"code": "..."}], "review": {"result": "PASS|FAIL", "findings": [...]}}'
)


def call_critic(goal_contract: str, diff: str = "", ci: str = "") -> dict:
    """Phase A input = goal_contract only; Phase B adds diff+ci. Stub without key."""
    if not os.getenv("MODEL_API_KEY"):
        sealed = [{"code": f"def test_goal():\n    assert {json.dumps(goal_contract[:60])} != ''  # sealed stub (Phase A)"}]
        review = {"result": "INCONCLUSIVE",
                  "findings": [{"note": "stub review (no MODEL_API_KEY); diff not trusted", "evidence": "none"}]}
        if diff:
            review["findings"].append({"note": "diff present but unverified without model", "evidence": "none"})
        return {"sealed_tests": sealed, "review": review, "stub": True,
                "model": os.getenv("MODEL_CRITIC", "muse-spark-1.3")}
    from openai import OpenAI
    client = OpenAI(base_url=os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1"),
                    api_key=os.environ["MODEL_API_KEY"])
    model = os.getenv("MODEL_CRITIC", "muse-spark-1.3")
    # Phase A then B as separate calls so builder context cannot leak in
    a = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": CRITIC_SYSTEM},
                  {"role": "user", "content": f"SPEC (Phase A, no diff shown):\n{goal_contract}"}],
        response_format={"type": "json_object"}, max_tokens=1500)
    sealed = json.loads(a.choices[0].message.content or "{}").get("sealed_tests", [])
    b = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": CRITIC_SYSTEM},
                  {"role": "user", "content": f"SPEC:\n{goal_contract}\nDIFF:\n{diff}\nCI:\n{ci}\nSEALED:\n{json.dumps(sealed)}"}],
        response_format={"type": "json_object"}, max_tokens=1500)
    data = json.loads(b.choices[0].message.content or "{}")
    data.setdefault("sealed_tests", sealed)
    data["stub"] = False
    data["model"] = model
    return data
