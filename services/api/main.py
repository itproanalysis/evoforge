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
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, StrictInt, model_validator

from evoforge import broker_meta, evidence as evidence_chain, ledger
from evoforge.patch import PatchError
from evoforge.kernel_api import router as kernel_router
from evoforge.commands import NeedsConfirmation, TransitionError, advance, create, get as get_cmd

ledger.configure({"default": int(os.getenv("EVO_PROJECT_BUDGET_CENTS", "50000"))})

app = FastAPI(title="EvoForge API", version="0.2.0-hackathon")
app.include_router(kernel_router)
# Web (Mission Control) is a separate origin locally and on Cloud Run; no cookies, so no credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv(
        "EVO_WEB_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()],
    allow_origin_regex=os.getenv(
        "EVO_WEB_ORIGIN_REGEX", r"https://evoforge-web-[a-z0-9-]+\.(a\.run\.app|[a-z0-9-]+\.run\.app)"),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
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
    vis_pass: StrictInt = Field(0, ge=0)
    vis_n: StrictInt = Field(0, ge=0)  # 0 runs = no execution evidence, never coerced to 1
    held_pass: StrictInt = Field(0, ge=0)
    held_n: StrictInt = Field(0, ge=0)

    @model_validator(mode="after")
    def _pass_within_runs(self):
        if self.vis_pass > self.vis_n or self.held_pass > self.held_n:
            raise ValueError("pass count exceeds run count")
        return self


class PRRequest(BaseModel):
    """Only a server-stored gate evaluation can back a PR; client diff/gates are ignored."""
    evidence_id: str
    title: str
    body: str = ""
    branch: str = ""
    base: str = "main"


class RunRequest(BaseModel):
    """Runs execute only the server-stored Critic sealed suite (T10).

    heldout_tests is deprecated and will be removed: it must be empty;
    any non-empty value is rejected with 422. The held-out suite comes
    solely from review_evidence_id (POST /v1/candidates/review evidence).
    """
    source_repo: str
    base_sha: str
    diff: str = ""
    tests: list[dict] = []
    heldout_tests: list[dict] = Field(
        default=[],
        description="Deprecated, for removal: must be empty; non-empty is 422. "
        "Held-out suite comes from review_evidence_id.",
    )
    review_evidence_id: str
    timeout_s: int = Field(120, ge=1, le=600)

    @model_validator(mode="after")
    def _no_client_heldout(self):
        if self.heldout_tests:
            raise ValueError(
                "heldout_tests is deprecated and must be empty; "
                "pass review_evidence_id pointing at server-stored review evidence"
            )
        return self


class SandboxRequest(BaseModel):
    source_repo: str
    base_sha: str
    future_shas: list[str] = []


class ObjectiveRequest(BaseModel):
    goal: str
    risk: str = "LOW"


class ReconcileRequest(BaseModel):
    reservation_id: str
    billed_cents: StrictInt | None = Field(default=None, ge=0)
    request_id: str | None = None


def _reserve_or_402(project: str = "default") -> str:
    try:
        return ledger.reserve(COST_CENTS, project)
    except Exception:
        raise HTTPException(402, "budget exhausted (reserve_cost refused)")


def _call_provider(rsv: str, fn, *args):
    """Refund only when the provider certainly did not accept; otherwise hold for reconciliation."""
    try:
        out = fn(*args)
    except broker_meta.ProviderNotAccepted as e:
        ledger.refund(rsv)
        raise HTTPException(502, f"provider not accepted; reservation {rsv} refunded")
    except Exception as e:
        ledger.mark_unknown(rsv, type(e).__name__)
        raise HTTPException(502, f"provider outcome unknown ({type(e).__name__}); "
                                 f"reservation {rsv} held for reconciliation")
    ledger.settle(rsv, COST_CENTS)  # the call happened, whatever the gates say next
    return out


def _link_stages(eid: str, stages) -> None:
    for stage in stages:
        evidence_chain.link(eid, stage, evidence_chain.record(stage, {"evidence_id": eid}))


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
    from evoforge.gates import evaluate_integrity

    candidate = _call_provider(rsv, broker_meta.call_builder, req.goal, req.repo_sha)
    verdicts = evaluate_integrity(candidate.get("diff", ""), candidate.get("tests", []))
    eid = _store_evidence({"command_id": cmd["command_id"], "candidate": candidate,
                           "reservation_id": rsv,
                           "gates": [v.__dict__ for v in verdicts]})
    _link_stages(eid, ("Task", "Candidate", "Gate"))
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
    _link_stages(eid, ("ObjectiveVersion",))
    return {"objective_id": oid, "evidence_id": eid, "goal": req.goal, "risk": req.risk}


@app.post("/v1/candidates/review")
def review(req: ReviewRequest):
    if os.getenv("MODEL_API_KEY"):
        # Real Critic calls have independent reservations and outcomes per phase.
        phase_evidence_ids = []
        def dispatch(send):
            phase = "critic_spec" if not phase_evidence_ids else "critic_review"
            rsv = _reserve_or_402()
            metadata = None
            response_document = None
            try:
                response = _call_provider(rsv, send)
                metadata = broker_meta.call_metadata(response, os.getenv("MODEL_CRITIC", "muse-spark-1.3"), phase)
                if hasattr(response, "model_dump"):
                    response_document = response.model_dump(mode="json")
                return response
            finally:
                phase_evidence_ids.append(_store_evidence({"kind": "provider_call", "phase": phase,
                    "reservation": ledger.reservation(rsv), "metadata": metadata,
                    "response_document": response_document}))
        out = broker_meta.call_critic(req.goal_contract, req.diff, req.ci, dispatch=dispatch)
        eid = _store_evidence({"review": out, "provider_evidence_ids": phase_evidence_ids})
        _link_stages(eid, ("Review",))
        return {**out, "evidence_id": eid, "provider_evidence_ids": phase_evidence_ids}
    rsv = _reserve_or_402()
    out = _call_provider(rsv, broker_meta.call_critic, req.goal_contract, req.diff, req.ci)
    eid = _store_evidence({"review": out})
    _link_stages(eid, ("Review",))
    return {**out, "evidence_id": eid}


@app.post("/v1/gates/evaluate")
def gates_evaluate(req: EvaluateRequest):
    from evoforge.gates import evaluate_full
    verdicts = evaluate_full(req.diff, req.tests, req.heldout_kinds,
                             req.vis_pass, req.vis_n, req.held_pass, req.held_n)
    gates = [v.__dict__ for v in verdicts]
    eid = _store_evidence({"diff": req.diff, "tests": req.tests, "gates": gates})
    return {"gates": gates, "evidence_id": eid}


@app.post("/v1/runs")
def runs(req: RunRequest):
    from evoforge import runner
    from evoforge.critic import ensure_sealed_suite
    from evoforge.gates import apply_run, evaluate_full
    if req.heldout_tests:
        # Defense in depth: the model validator already 422s non-empty
        # client suites; never fall back to them here.
        raise HTTPException(422, "heldout_tests is deprecated and must be empty; "
                                 "pass review_evidence_id pointing at server-stored review evidence")
    src = _evidence.get(req.review_evidence_id)
    if src is None:
        raise HTTPException(404, "unknown review evidence id")
    inner = src.get("review")
    if not isinstance(inner, dict):
        raise HTTPException(409, f"evidence {req.review_evidence_id} is not a review")
    if inner.get("stub") is True:
        raise HTTPException(409, f"evidence {req.review_evidence_id} is a stub review "
                                 "and cannot back a run")
    sealed = inner.get("sealed_tests")
    ok, normalized, _findings = ensure_sealed_suite(sealed)
    if not ok:
        raise HTTPException(409, f"evidence {req.review_evidence_id} has an invalid sealed suite")
    try:
        run = runner.run_candidate(req.source_repo, req.base_sha, req.diff,
                                   req.tests, normalized,
                                   timeout_s=req.timeout_s)
    except runner.RunnerError as e:
        raise HTTPException(400, str(e))
    except PatchError as e:
        raise HTTPException(409, str(e))
    verdicts = evaluate_full(req.diff, req.tests,
                             [k for k in run["heldout_kinds"] if k],
                             run["visible"]["pass"], run["visible"]["n"],
                             run["heldout"]["pass"], run["heldout"]["n"])
    # GH_INTEGRITY judges gaming; whether the required tests pass is G2_REQUIRED's job.
    gates = [v.__dict__ for v in apply_run(verdicts, run)]
    eid = _store_evidence({"diff": req.diff, "tests": req.tests, "gates": gates,
                           "run": run, "source_repo": req.source_repo,
                           "base_sha": req.base_sha,
                           "review_evidence_id": req.review_evidence_id})
    _link_stages(eid, ("Candidate", "Gate"))
    return {"gates": gates, "run": run, "evidence_id": eid}


@app.post("/v1/pr/create")
def pr_create(req: PRRequest):
    from evoforge import github

    src = _evidence.get(req.evidence_id)
    if src is None:
        raise HTTPException(404, "unknown evidence id")
    gates = src.get("gates")
    if not isinstance(src.get("diff"), str) or not gates:
        raise HTTPException(409, f"evidence {req.evidence_id} is not a gate evaluation")
    if not isinstance(src.get("run"), dict):
        raise HTTPException(409, f"evidence {req.evidence_id} has no server run; "
                                 "PRs require a /v1/runs server execution "
                                 "(client-reported counts cannot back a PR)")
    blocked = [f"{g['gate']}={g['result']}" for g in gates if g.get("result") != "PASS"]
    if blocked:
        raise HTTPException(409, f"PR blocked by gates: {', '.join(blocked)}")
    body = "\n".join([req.body, "", *(f"{g['gate']}={g['result']} ({g.get('reason', '')})" for g in gates),
                      f"Evidence: {req.evidence_id}"])
    try:
        pr = github.create_pr(src["diff"], req.title, body,
                              req.branch or f"evoforge/{uuid.uuid4().hex[:8]}", req.base)
    except PatchError as e:
        raise HTTPException(409, str(e))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    eid = _store_evidence({"pr": pr.get("html_url"), "title": req.title,
                           "source_evidence_id": req.evidence_id})
    for entry in evidence_chain.chain(req.evidence_id):
        if entry.get("event_id") is not None:
            evidence_chain.link(eid, entry["stage"], entry["event_id"])
    _link_stages(eid, ("PR",))
    return {"pr": pr, "evidence_id": eid, "source_evidence_id": req.evidence_id}


@app.post("/v1/eval/sandbox")
def eval_sandbox(req: SandboxRequest):
    from evoforge import runner
    from evoforge.hygiene_api import run_sandbox
    try:
        runner.allowed_repo(req.source_repo)
    except runner.RunnerError as e:
        raise HTTPException(400, str(e))
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
    stored = _evidence[eid]
    data = {k: v for k, v in stored.items() if k not in ("chain", "data")}
    return {**stored, "chain": evidence_chain.chain(eid), "data": data}


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


@app.post("/v1/ledger/reconcile")
def ledger_reconcile(req: ReconcileRequest):
    try:
        result = ledger.reconcile(req.reservation_id, req.billed_cents, req.request_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    eid = _store_evidence(result)
    return {**result, "evidence_id": eid}


@app.get("/v1/ledger")
def ledger_snapshot():
    return ledger.snapshot("default")
