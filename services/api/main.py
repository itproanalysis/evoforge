"""EvoForge API — Trust Kernel outside LLM (D-006/D-007).

Call path (p.09, Phase 3): allowlist -> reserve_cost -> side_effect_intents
-> Meta Model API -> receipt -> settle. No LiteLLM, official SDK only (D-017).
Amounts are integer cents, never float.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "docs", "evoforge-v4.2", "reference_impl"))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="EvoForge API", version="0.1.0-hackathon")


class GenerateRequest(BaseModel):
    goal: str
    repo_sha: str = "HEAD"
    risk: str = "LOW"  # LOW | HIGH | CRITICAL (vocabulary.json)


class GateVerdict(BaseModel):
    gate: str
    result: str  # PASS | FAIL | INCONCLUSIVE
    reason: str = ""


@app.get("/healthz")
def healthz():
    return {"ok": True, "kernel": "trust-closed", "model_base": os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1")}


@app.post("/v1/commands/generate")
def generate(req: GenerateRequest):
    """Vertical slice H1: reserve budget, call Muse Spark Builder, run GH_INTEGRITY."""
    if not req.goal.strip():
        raise HTTPException(400, "goal required")
    # reserve_cost (stub: real impl = core.reserve_cost in Postgres; fail-closed)
    budget_cents = int(os.getenv("EVO_PROJECT_BUDGET_CENTS", "50000"))
    if budget_cents <= 0:
        raise HTTPException(402, "budget exhausted (reserve_cost refused)")
    command_id = f"cmd_{uuid.uuid4().hex[:12]}"
    # Meta call happens in broker_meta.call_builder (lazy import so tests run w/o key)
    from evoforge.broker_meta import call_builder

    candidate = call_builder(req.goal, req.repo_sha)
    from evoforge.gates import evaluate_integrity

    verdicts = evaluate_integrity(candidate["diff"], candidate["tests"])
    return {
        "command_id": command_id,
        "candidate": candidate,
        "gates": [v.__dict__ for v in verdicts],
        "budget_reserved_cents": 120,  # max-tokens conservative estimate
        "evidence": {"repo_sha": req.repo_sha, "model": os.getenv("MODEL_BUILDER", "muse-spark-1.3")},
    }
