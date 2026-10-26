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

from evoforge import ledger
from evoforge.commands import NeedsConfirmation, TransitionError, advance, create, get as get_cmd

ledger.configure({"default": int(os.getenv("EVO_PROJECT_BUDGET_CENTS", "50000"))})

app = FastAPI(title="EvoForge API", version="0.2.0-hackathon")
_evidence: dict[str, dict] = {}  # in-memory evidence store
COST_CENTS = 120  # conservative per-model-call estimate (int cents)


class GenerateRequest(BaseModel):
    goal: str
    repo_sha: str = "HEAD"
    risk: str = "LOW"
    idempotency_key: str | None = None
    confirm: bool = False


class GateVerdict(BaseModel):
    gate: str
    result: str  # PASS | FAIL | INCONCLUSIVE
    reason: str = ""


class ReviewRequest(BaseModel):
    goal_contract: str
    diff: str = ""
    ci: str = ""


class EvaluateRequest(BaseModel):
    diff: str
    tests: list[dict] = []
    heldout_kinds: list[str] = []
    vis_pass: int = 0
    vis_n: int = 1
    held_pass: int = 0
    held_n: int = 1


class PRRequest(BaseModel):
    diff: str
    title: str
    body: str = ""
    branch: str = ""
    base: str = "main"
    gates: list[dict] = []
    wvi_link: str = ""


class SandboxRequest(BaseModel):
    source_repo: str
    base_sha: str
    future_shas: list[str] = []


class ObjectiveRequest(BaseModel):
    goal: str
    risk: str = "LOW"


def _reserve_or_402(project: str = "default") -> str:
    try:
        return ledger.reserve(COST_CENTS, project)
    except Exception:
        raise HTTPException(402, "budget exhausted (reserve_cost refused)")


def _store_evidence(payload: dict) -> str:
    eid = f"ev_{uuid.uuid4().hex[:12]}"
    _evidence[eid] = {"id": eid, "ts": time.time(), **payload}
    return eid


@app.get("/healthz")
def healthz():
    return {"ok": True, "kernel": "trust-closed",
            "model_base": os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1")}


@app.post("/v1/commands/generate")
def generate(req: GenerateRequest):
    """Vertical slice H1: reserve budget, call Muse Spark Builder, run GH_INTEGRITY."""
    if not req.goal.strip():
        raise HTTPException(400, "goal required")
    key = req.idempotency_key or f"gen:{req.goal}:{req.repo_sha}"
    try:
        cmd = create(req.goal, key, kind="BUILD", risk=req.risk, confirm=req.confirm)
    except NeedsConfirmation as e:
        raise HTTPException(409, str(e))
    except TransitionError as e:
        raise HTTPException(409, str(e))
    if cmd.get("served"):
        return cmd["served"]
    rsv = _reserve_or_402()
    from evoforge.broker_meta import call_builder
    from evoforge.gates import evaluate_integrity

    candidate = call_builder(req.goal, req.repo_sha)
    verdicts = evaluate_integrity(candidate["diff"], candidate["tests"])
    ledger.settle(rsv, COST_CENTS)
    eid = _store_evidence({"command_id": cmd["command_id"], "candidate": candidate,
                           "gates": [v.__dict__ for v in verdicts]})
    body = {"command_id": cmd["command_id"], "candidate": candidate,
            "gates": [v.__dict__ for v in verdicts],
            "budget_reserved_cents": COST_CENTS,
            "evidence": {"id": eid, "repo_sha": req.repo_sha,
                         "model": os.getenv("MODEL_BUILDER", "muse-spark-1.3")}}
    cmd["served"] = body
    return body


@app.post("/v1/objectives")
def objectives(req: ObjectiveRequest):
    if not req.goal.strip():
        raise HTTPException(400, "goal required")
    oid = f"obj_{uuid.uuid4().hex[:12]}"
    eid = _store_evidence({"objective_id": oid, "goal": req.goal, "risk": req.risk})
    return {"objective_id": oid, "evidence_id": eid, "goal": req.goal, "risk": req.risk}


@app.post("/v1/candidates/review")
def review(req: ReviewRequest):
    rsv = _reserve_or_402()
    from evoforge.broker_meta import call_critic
    out = call_critic(req.goal_contract, req.diff)
    ledger.settle(rsv, COST_CENTS)
    eid = _store_evidence({"review": out})
    return {**out, "evidence_id": eid}


@app.post("/v1/gates/evaluate")
def gates_evaluate(req: EvaluateRequest):
    from evoforge.gates import evaluate_full
    verdicts = evaluate_full(req.diff, req.tests, req.heldout_kinds,
                             req.vis_pass, req.vis_n, req.held_pass, req.held_n)
    eid = _store_evidence({"gates": [v.__dict__ for v in verdicts]})
    return {"gates": [v.__dict__ for v in verdicts], "evidence_id": eid}


@app.post("/v1/pr/create")
def pr_create(req: PRRequest):
    from evoforge.github import create_pr
    body = (req.body + "\n\nGates: "
            + "; ".join(f"{g.get('gate')}={g.get('result')}" for g in req.gates)
            + (f"\nWVI: {req.wvi_link}" if req.wvi_link else ""))
    try:
        pr = create_pr(req.diff, req.title, body, req.branch or f"evoforge/{uuid.uuid4().hex[:8]}", req.base)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    eid = _store_evidence({"pr": pr.get("html_url"), "title": req.title})
    return {"pr": pr, "evidence_id": eid}


@app.post("/v1/eval/sandbox")
def eval_sandbox(req: SandboxRequest):
    from evoforge.hygiene_api import run_sandbox
    try:
        out = run_sandbox(req.source_repo, req.base_sha, req.future_shas)
    except Exception as e:
        raise HTTPException(400, f"sandbox failed: {e}")
    eid = _store_evidence({"sandbox": out})
    return {**out, "evidence_id": eid}


@app.get("/v1/evidence/{eid}")
def evidence(eid: str):
    if eid not in _evidence:
        raise HTTPException(404, "unknown evidence id")
    return _evidence[eid]


@app.get("/v1/commands/{command_id}")
def command_status(command_id: str):
    cmd = get_cmd(command_id)
    if cmd is None:
        raise HTTPException(404, "unknown command")
    return cmd


@app.post("/v1/commands/{command_id}/advance")
def command_advance(command_id: str, to_state: str):
    try:
        return advance(command_id, to_state)
    except (KeyError, TransitionError) as e:
        raise HTTPException(400, str(e))
