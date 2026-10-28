"""EvoForge API — Trust Kernel outside LLM (D-006/D-007).

Call path (p.09, Phase 3): allowlist -> reserve_cost -> side_effect_intents
-> Meta Model API -> receipt -> settle. No LiteLLM, official SDK only (D-017).
Amounts are integer cents, never float.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "docs", "evoforge-v4.2", "reference_impl"))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictInt, model_validator
from typing import Literal

from evoforge import auth as auth_module
from evoforge import broker_meta, evidence as evidence_chain, ledger
from evoforge import outcomes as outcomes_store
from evoforge import performance as performance_mod
from evoforge import sealed_eval as sealed_eval_mod
from evoforge import postgres_state
from evoforge.postgres_kernel import KernelRejected, KernelUnavailable
from evoforge.patch import PatchError
from evoforge.kernel_api import router as kernel_router
from evoforge.commands import NeedsConfirmation, TransitionError, advance, create, get as get_cmd
from evoforge import missions as missions_store
from evoforge.missions import NeedsConfirmation as MissionNeedsConfirmation
from evoforge.missions import TransitionError as MissionTransitionError

ledger.configure({"default": int(os.getenv("EVO_PROJECT_BUDGET_CENTS", "50000"))})

app = FastAPI(title="EvoForge API", version="0.2.0-hackathon")


@app.exception_handler(KernelUnavailable)
async def state_unavailable(request: Request, exc):
    return JSONResponse({"detail": "state storage unavailable"}, status_code=503)


@app.exception_handler(KernelRejected)
async def state_rejected(request: Request, exc):
    return JSONResponse({"detail": "state storage rejected the operation"}, status_code=409)
app.include_router(kernel_router)
# Web (Mission Control) is a separate origin locally and on Cloud Run; no cookies, so no credentials.
# Explicit origins apply when EVO_WEB_ORIGINS / EVO_WEB_ORIGIN_REGEX are set.
_WEB_ORIGINS = [o.strip() for o in os.getenv(
    "EVO_WEB_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]
_WEB_ORIGIN_REGEX = os.getenv(
    "EVO_WEB_ORIGIN_REGEX", r"https://evoforge-web-[a-z0-9-]+\.(a\.run\.app|[a-z0-9-]+\.run\.app)").strip() or None
app.add_middleware(
    CORSMiddleware,
    allow_origins=_WEB_ORIGINS,
    allow_origin_regex=_WEB_ORIGIN_REGEX,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
_evidence = postgres_state.ScopedRecords("records")  # postgres when configured, memory in dev
COST_CENTS = 120  # conservative per-model-call estimate (int cents)


def _expected_api_audience() -> str:
    return (os.getenv("EVO_API_URL", "").strip()
            or os.getenv("EVO_API_AUDIENCE", "").strip())


@app.middleware("http")
async def _require_google_id_token(request: Request, call_next):
    path = request.url.path
    if os.getenv("EVO_REQUIRE_ID_TOKEN", "0") == "1" and path.startswith("/v1/"):
        authz = request.headers.get("authorization", "")
        if not authz or not authz.lower().startswith("bearer "):
            return JSONResponse({"detail": "missing ID token"}, status_code=401)
        token = authz[7:].strip()
        if not token:
            return JSONResponse({"detail": "missing ID token"}, status_code=401)
        audience = _expected_api_audience()
        try:
            claims = auth_module.verify_id_token(token, audience)
        except ValueError as e:
            msg = str(e).lower()
            if "audience" in msg or "aud" in msg:
                return JSONResponse({"detail": "invalid token audience"}, status_code=403)
            return JSONResponse({"detail": "invalid ID token"}, status_code=401)
        except Exception:
            return JSONResponse({"detail": "invalid ID token"}, status_code=401)
        if audience:
            aud = claims.get("aud")
            if isinstance(aud, list):
                ok = audience in aud
            else:
                ok = aud == audience
            if not ok:
                return JSONResponse({"detail": "invalid token audience"}, status_code=403)
        allow_svc = os.getenv("EVO_WEB_SERVICE_ACCOUNT", "").strip()
        if allow_svc:
            email = claims.get("email")
            if email is not None and email != allow_svc:
                return JSONResponse({"detail": "forbidden service account"}, status_code=403)
        request.state.id_token_claims = claims
    return await call_next(request)


class GenerateRequest(BaseModel):
    goal: str
    repo_sha: str = "HEAD"
    risk: str = "LOW"
    idempotency_key: str | None = None
    confirm: bool = False
    target_paths: list | None = None


_BUILDER_MAX_PATHS = 10
_BUILDER_PER_FILE_CAP = 32 * 1024
_BUILDER_TOTAL_CAP = 128 * 1024


def _validate_target_paths(paths) -> list[str]:
    import re

    if not isinstance(paths, list):
        raise HTTPException(400, "target_paths must be a list of relative POSIX paths")
    if len(paths) > _BUILDER_MAX_PATHS:
        raise HTTPException(400, f"target_paths limited to {_BUILDER_MAX_PATHS} entries")
    out: list[str] = []
    for p in paths:
        if not isinstance(p, str) or not p:
            raise HTTPException(400, f"bad target path: {p!r}")
        if len(p) > 120:
            raise HTTPException(400, f"bad target path (over 120 chars): {p!r}")
        if "\\" in p or p.startswith("/"):
            raise HTTPException(400, f"bad target path: {p!r}")
        if re.match(r"^[A-Za-z]:", p):
            raise HTTPException(400, f"bad target path: {p!r}")
        segs = p.split("/")
        if any(s == "" for s in segs):
            raise HTTPException(400, f"bad target path: {p!r}")
        if ".." in segs:
            raise HTTPException(400, f"bad target path: {p!r}")
        if segs[0] == ".git":
            raise HTTPException(400, f"bad target path: {p!r}")
        out.append(p)
    return out


def _load_builder_context(repo_sha: str, target_paths: list[str]) -> list[dict]:
    """Read target files at the T15-resolved base; 400 bad/missing, 413 over cap."""
    import shutil

    from evoforge import repo_source as _rs

    try:
        resolved = _rs.resolve_repo_dir("", repo_sha)
    except Exception as e:
        raise HTTPException(400, _rs.redact(str(e)))
    try:
        root = os.path.realpath(resolved)
        ctx: list[dict] = []
        total = 0
        for p in target_paths:
            full = os.path.join(resolved, p)
            try:
                real = os.path.realpath(full)
                if os.path.commonpath([root, real]) != root:
                    raise HTTPException(400, f"bad target path: {p!r}")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(400, f"bad target path: {p!r}")
            if not os.path.isfile(real) or os.path.islink(full) and not os.path.isfile(real):
                raise HTTPException(400, f"target file not found at base: {p}")
            try:
                size = os.path.getsize(real)
            except OSError:
                raise HTTPException(400, f"target file not found at base: {p}")
            if size > _BUILDER_PER_FILE_CAP:
                raise HTTPException(413, f"target file over per-file budget (32KB): {p}")
            if total + size > _BUILDER_TOTAL_CAP:
                raise HTTPException(413, f"target files over total budget (128KB) at: {p}")
            try:
                with open(real, "rb") as fh:
                    raw = fh.read()
            except OSError:
                raise HTTPException(400, f"target file not found at base: {p}")
            if len(raw) > _BUILDER_PER_FILE_CAP:
                raise HTTPException(413, f"target file over per-file budget (32KB): {p}")
            if total + len(raw) > _BUILDER_TOTAL_CAP:
                raise HTTPException(413, f"target files over total budget (128KB) at: {p}")
            if b"\x00" in raw:
                ctx.append({"path": p, "skipped": "binary/too-large"})
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                ctx.append({"path": p, "skipped": "binary/too-large"})
                continue
            total += len(raw)
            ctx.append({"path": p, "content": text})
        return ctx
    finally:
        try:
            base = os.path.basename(resolved.rstrip(os.sep))
            if base.startswith("evoforge-remote-"):
                shutil.rmtree(resolved, ignore_errors=True)
        except Exception:
            pass


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
    postgres_state.ensure_ready()  # reject unavailable state before any provider reservation/call
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


def _stage_summary(eid: str, stage: str) -> dict:
    """Per-stage facts already stored server-side; never includes test code."""
    stored = _evidence.get(eid, {})
    if stage == "ObjectiveVersion":
        return {
            "objective_id": stored.get("objective_id"),
            "goal": stored.get("goal"),
            "risk": stored.get("risk"),
        }
    if stage == "Task":
        return {"command_id": stored.get("command_id")}
    if stage == "Candidate":
        cand = stored.get("candidate")
        diff = ""
        tests: list = []
        stub = None
        if isinstance(cand, dict):
            d = cand.get("diff")
            if isinstance(d, str):
                diff = d
            t = cand.get("tests")
            if isinstance(t, list):
                tests = t
            stub = cand.get("stub")
        if not diff and isinstance(stored.get("diff"), str):
            diff = stored["diff"]
        if not tests and isinstance(stored.get("tests"), list):
            tests = stored["tests"]
        return {
            "tests_count": len(tests),
            "diff_chars": len(diff),
            "stub": stub,
        }
    if stage == "Gate":
        gates = stored.get("gates") if isinstance(stored.get("gates"), list) else []
        verdicts = [
            {"gate": g.get("gate"), "result": g.get("result"), "reason": g.get("reason", "")}
            for g in gates if isinstance(g, dict)
        ]
        summary: dict = {"verdicts": verdicts, "gates": verdicts}
        run = stored.get("run")
        if isinstance(run, dict):
            vis = run.get("visible") if isinstance(run.get("visible"), dict) else {}
            held = run.get("heldout") if isinstance(run.get("heldout"), dict) else {}
            summary["visible"] = {"pass": vis.get("pass"), "n": vis.get("n")}
            summary["heldout"] = {"pass": held.get("pass"), "n": held.get("n")}
            summary["run_counts"] = {
                "vis_pass": vis.get("pass"), "vis_n": vis.get("n"),
                "held_pass": held.get("pass"), "held_n": held.get("n"),
            }
            kinds = run.get("heldout_kinds")
            if isinstance(kinds, list):
                summary["heldout_kinds"] = [k for k in kinds if isinstance(k, str)]
        return summary
    if stage == "Review":
        inner = stored.get("review")
        sealed: list = []
        review_doc: dict = {}
        stub = None
        model = None
        if isinstance(inner, dict):
            s = inner.get("sealed_tests")
            if isinstance(s, list):
                sealed = s
            r = inner.get("review")
            if isinstance(r, dict):
                review_doc = r
            stub = inner.get("stub")
            model = inner.get("model")
        result = review_doc.get("result")
        findings = review_doc.get("findings") if isinstance(review_doc.get("findings"), list) else []
        kinds = sorted({t.get("kind") for t in sealed if isinstance(t, dict) and isinstance(t.get("kind"), str)})
        return {
            "result": result,
            "review_result": result,
            "review": {"result": result},
            "findings_count": len(findings),
            "sealed_count": len(sealed),
            "sealed_kinds": kinds,
            "stub": stub,
            "model": model,
        }
    if stage == "PR":
        pr_url = stored.get("pr")
        return {
            "pr": pr_url,
            "pr_url": pr_url,
            "html_url": pr_url,
            "title": stored.get("title"),
            "source_evidence_id": stored.get("source_evidence_id"),
        }
    if stage == "Outcome":
        xs = stored.get("X_SINGLE") if isinstance(stored.get("X_SINGLE"), dict) else {}
        return {
            "baseline_id": stored.get("baseline_id"),
            "suite_version": stored.get("suite_version"),
            "model": stored.get("model"),
            "X_SINGLE": {k: xs.get(k) for k in ("pass_rate", "n", "cost_cents")},
            "pass_rate": xs.get("pass_rate"),
            "n": xs.get("n"),
            "cost_cents": xs.get("cost_cents"),
        }
    return {}


def _link_stages(eid: str, stages) -> None:
    for stage in stages:
        event_id = evidence_chain.record(stage, None, evidence_id=eid, summary=_stage_summary(eid, stage))
        evidence_chain.link(eid, stage, event_id)


def _redact_sealed_entry(entry):
    """One sealed test -> {kind, code_sha256, code_len}; raw code never leaves."""
    if isinstance(entry, dict):
        kind = entry.get("kind")
        code = entry.get("code")
        if isinstance(code, str):
            digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
            ln = len(code)
        else:
            digest = ""
            ln = 0
        return {"kind": kind, "code_sha256": digest, "code_len": ln}
    if isinstance(entry, str):
        return {"kind": "", "code_sha256": hashlib.sha256(entry.encode("utf-8")).hexdigest(),
                "code_len": len(entry)}
    return {"kind": "", "code_sha256": "", "code_len": 0}


def _redact_sealed_list(tests: list) -> list:
    return [_redact_sealed_entry(t) for t in tests]


def _sealed_counts(tests: list) -> dict:
    kinds = sorted({t.get("kind") for t in tests
                    if isinstance(t, dict) and isinstance(t.get("kind"), str)})
    return {"sealed_count": len(tests), "sealed_tests_count": len(tests),
            "sealed_kinds": kinds}


def _redact_value(value):
    """Public copy helper: strip sealed test code and provider response bodies.

    Raw records stay in the server store; this builds a redacted copy for HTTP.
    Every sealed_tests list becomes [{kind, code_sha256, code_len}] plus counts.
    """
    if isinstance(value, dict):
        if "response_document" in value:
            out = {}
            for k, v in value.items():
                if k == "response_document":
                    out[k] = {"redacted": True}
                elif k == "sealed_tests" and isinstance(v, list):
                    out[k] = _redact_sealed_list(v)
                else:
                    out[k] = _redact_value(v)
            if isinstance(value.get("sealed_tests"), list):
                for ck, cv in _sealed_counts(value["sealed_tests"]).items():
                    out.setdefault(ck, cv)
            return out
        if isinstance(value.get("sealed_tests"), list):
            out = {}
            for k, v in value.items():
                if k == "sealed_tests":
                    out[k] = _redact_sealed_list(v)
                else:
                    out[k] = _redact_value(v)
            for ck, cv in _sealed_counts(value["sealed_tests"]).items():
                out.setdefault(ck, cv)
            return out
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(x) for x in value]
    return value


def _store_evidence(payload: dict) -> str:
    eid = f"ev_{uuid.uuid4().hex[:12]}"
    _evidence[eid] = {"id": eid, "ts": time.time(), **payload}
    return eid


def _generate_core(*, goal: str, base_sha: str, file_context: list[dict] | None,
                   store_extra: dict) -> tuple[str, dict, list]:
    """Shared reserve -> Builder -> GH_INTEGRITY -> store -> link core.

    ONE implementation backs POST /v1/commands/generate and the mission
    GENERATED step; idempotency/response shaping lives in the callers.
    """
    rsv = _reserve_or_402()
    from evoforge.gates import evaluate_integrity

    if file_context:
        candidate = _call_provider(rsv, broker_meta.call_builder, goal,
                                   base_sha, file_context)
    else:
        candidate = _call_provider(rsv, broker_meta.call_builder, goal,
                                   base_sha)
    verdicts = evaluate_integrity(candidate.get("diff", ""), candidate.get("tests", []))
    eid = _store_evidence({"candidate": candidate, "reservation_id": rsv,
                           "gates": [v.__dict__ for v in verdicts], **store_extra})
    _link_stages(eid, ("Task", "Candidate", "Gate"))
    return eid, candidate, verdicts


def _review_core(*, goal_contract: str, diff: str, ci: str,
                 store_extra: dict) -> tuple[str, dict, list]:
    """Shared reserve -> Critic -> store -> link core.

    ONE implementation backs POST /v1/candidates/review and the mission
    REVIEWED step; HTTP shaping / mission attach live in the callers.
    Returns (evidence_id, raw_critic_output, phase_evidence_ids).
    """
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
        out = broker_meta.call_critic(goal_contract, diff, ci, dispatch=dispatch)
        eid = _store_evidence({"review": out, "provider_evidence_ids": phase_evidence_ids,
                               **store_extra})
        _link_stages(eid, ("Review",))
        return eid, out, phase_evidence_ids
    rsv = _reserve_or_402()
    out = _call_provider(rsv, broker_meta.call_critic, goal_contract, diff, ci)
    eid = _store_evidence({"review": out, **store_extra})
    _link_stages(eid, ("Review",))
    return eid, out, []


def _validated_sealed_suite(review_evidence_id: str) -> list:
    """Shared review-evidence gate for runs: 404 unknown, 409 not-a-review/stub/bad-suite."""
    from evoforge.critic import ensure_sealed_suite

    src = _evidence.get(review_evidence_id)
    if src is None:
        raise HTTPException(404, "unknown review evidence id")
    inner = src.get("review")
    if not isinstance(inner, dict):
        raise HTTPException(409, f"evidence {review_evidence_id} is not a review")
    if inner.get("stub") is True:
        raise HTTPException(409, f"evidence {review_evidence_id} is a stub review "
                                 "and cannot back a run")
    sealed = inner.get("sealed_tests")
    ok, normalized, _findings = ensure_sealed_suite(sealed)
    if not ok:
        raise HTTPException(409, f"evidence {review_evidence_id} has an invalid sealed suite")
    return normalized


def _run_core(*, source_repo: str, base_sha: str, diff: str, tests: list,
              review_evidence_id: str, timeout_s: int,
              store_extra: dict) -> tuple[str, list, dict]:
    """Shared sealed-run core: validate the server-stored review, execute via
    the isolated Runner whenever EVO_RUNNER_URL is set (candidate code never
    runs in the API process then), judge gates, store evidence and link
    Candidate/Gate plus the review's own Review-stage event.

    ONE implementation backs POST /v1/runs and the mission RAN step.
    """
    from evoforge.gates import apply_run, evaluate_full

    normalized = _validated_sealed_suite(review_evidence_id)
    runner_url = (os.getenv("EVO_RUNNER_URL", "") or "").strip()
    if runner_url:
        run = _run_remote(source_repo, base_sha, diff, tests, normalized, timeout_s)
    else:
        run = _run_local(source_repo, base_sha, diff, tests, normalized, timeout_s)
    verdicts = evaluate_full(diff, tests,
                             [k for k in run["heldout_kinds"] if k],
                             run["visible"]["pass"], run["visible"]["n"],
                             run["heldout"]["pass"], run["heldout"]["n"])
    # GH_INTEGRITY judges gaming; whether the required tests pass is G2_REQUIRED's job.
    gates = [v.__dict__ for v in apply_run(verdicts, run)]
    eid = _store_evidence({"diff": diff, "tests": tests, "gates": gates,
                           "run": run, "source_repo": source_repo,
                           "base_sha": base_sha,
                           "review_evidence_id": review_evidence_id, **store_extra})
    _link_stages(eid, ("Candidate", "Gate"))
    # Link the run into the review's chain: reuse the review evidence's
    # Review-stage event (never re-record, never mutate the review evidence).
    # A missing Review stage stays null; it never 500s.
    for entry in evidence_chain.chain(review_evidence_id):
        if entry.get("stage") == "Review" and entry.get("event_id") is not None:
            evidence_chain.link(eid, "Review", entry["event_id"])
            break
    return eid, gates, run


def _pr_core(*, source_evidence_id: str, title: str, body_intro: str,
             branch: str, base: str, store_extra: dict) -> tuple[str, dict]:
    """Shared all-PASS server-run gate -> create_pr -> store -> chain-copy core.

    ONE implementation backs POST /v1/pr/create and the mission PR_OPENED step.
    """
    from evoforge import github

    src = _evidence.get(source_evidence_id)
    if src is None:
        raise HTTPException(404, "unknown evidence id")
    gates = src.get("gates")
    if not isinstance(src.get("diff"), str) or not gates:
        raise HTTPException(409, f"evidence {source_evidence_id} is not a gate evaluation")
    if not isinstance(src.get("run"), dict):
        raise HTTPException(409, f"evidence {source_evidence_id} has no server run; "
                                 "PRs require a /v1/runs server execution "
                                 "(client-reported counts cannot back a PR)")
    verified_base = src["run"].get("base")
    if not isinstance(verified_base, str) or not re.fullmatch(r"[0-9a-f]{40}", verified_base):
        raise HTTPException(409, "server run has no immutable Git base SHA")
    blocked = [f"{g['gate']}={g['result']}" for g in gates if g.get("result") != "PASS"]
    if blocked:
        raise HTTPException(409, f"PR blocked by gates: {', '.join(blocked)}")
    extra_files: dict[str, str] = {}
    stored_tests = src.get("tests")
    # Unique per source evidence: repeated missions on the same base must not
    # collide with test files an earlier mission already merged.
    tag = re.sub(r"[^0-9a-z]", "", (source_evidence_id or "").lower().replace("ev_", ""))[:8] or "gen"
    if isinstance(stored_tests, list):
        for i, t in enumerate(stored_tests, 1):
            if not isinstance(t, dict):
                continue
            code = t.get("code")
            if not isinstance(code, str) or code == "":
                continue
            extra_files[f"tests/evoforge_gen/test_{tag}_{i}.py"] = code
    for p in extra_files:
        segs = p.split("/")
        if "" in segs or ".." in segs or not p.startswith("tests/evoforge_gen/"):
            raise HTTPException(409, f"test file path escapes tests/evoforge_gen/: {p}")
    if extra_files:
        try:
            from evoforge.patch import paths_in_diff as _paths_in_diff

            dpaths = set(_paths_in_diff(src["diff"]))
        except Exception:
            dpaths = set()
        for p in extra_files:
            if p in dpaths:
                raise HTTPException(409, f"test file path collides with diff: {p}")
    body = "\n".join([body_intro, "",
                      *(f"{g['gate']}={g['result']} ({g.get('reason', '')})" for g in gates),
                      f"Evidence: {source_evidence_id}"])
    if extra_files:
        body = body + f"\nTests: {', '.join(sorted(extra_files))}"
    try:
        pr = github.create_pr(src["diff"], title, body,
                              branch, base,
                              extra_files=extra_files or None,
                              expected_base_sha=verified_base)
    except PatchError as e:
        raise HTTPException(409, str(e))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    eid = _store_evidence({"pr": pr.get("html_url"), "title": title,
                           "source_evidence_id": source_evidence_id, **store_extra})
    for entry in evidence_chain.chain(source_evidence_id):
        if entry.get("event_id") is not None:
            evidence_chain.link(eid, entry["stage"], entry["event_id"])
    _link_stages(eid, ("PR",))
    return eid, pr


@app.get("/healthz")
def healthz():
    return {"ok": True, "kernel": "trust-closed",
            "model_base": os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1")}


@app.post("/v1/commands/generate")
def generate(req: GenerateRequest):
    """Vertical slice H1: reserve budget, call Muse Spark Builder, run GH_INTEGRITY."""
    postgres_state.ensure_ready()  # storage failure must not poison command creation/replay
    if not req.goal.strip():
        raise HTTPException(400, "goal required")
    validated_paths: list[str] | None = None
    file_context: list[dict] | None = None
    if req.target_paths is not None:
        validated_paths = _validate_target_paths(req.target_paths)
        if validated_paths:
            file_context = _load_builder_context(req.repo_sha, validated_paths)
    suffix = f":{','.join(validated_paths)}" if validated_paths else ""
    key = req.idempotency_key or f"gen:{req.goal}:{req.repo_sha}{suffix}"
    try:
        cmd = create(req.goal, key, kind="BUILD", risk=req.risk, confirm=req.confirm)
    except NeedsConfirmation as e:
        raise HTTPException(409, str(e))
    except TransitionError as e:
        raise HTTPException(409, str(e))
    if cmd.get("served"):
        return cmd["served"]
    eid, candidate, verdicts = _generate_core(
        goal=req.goal, base_sha=req.repo_sha, file_context=file_context,
        store_extra={"command_id": cmd["command_id"]})
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
        eid, out, phase_evidence_ids = _review_core(
            goal_contract=req.goal_contract, diff=req.diff, ci=req.ci, store_extra={})
        public = _redact_value(out)
        return {**public, "evidence_id": eid, "provider_evidence_ids": phase_evidence_ids}
    eid, out, _ = _review_core(
        goal_contract=req.goal_contract, diff=req.diff, ci=req.ci, store_extra={})
    public = _redact_value(out)
    return {**public, "evidence_id": eid}


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
    if req.heldout_tests:
        # Defense in depth: the model validator already 422s non-empty
        # client suites; never fall back to them here.
        raise HTTPException(422, "heldout_tests is deprecated and must be empty; "
                                 "pass review_evidence_id pointing at server-stored review evidence")
    eid, gates, run = _run_core(
        source_repo=req.source_repo, base_sha=req.base_sha, diff=req.diff,
        tests=req.tests, review_evidence_id=req.review_evidence_id,
        timeout_s=req.timeout_s, store_extra={})
    return {"gates": gates, "run": run, "evidence_id": eid}


def _run_local(source_repo: str, base_sha: str, diff: str, tests: list,
               normalized: list, timeout_s: int = 120) -> dict:
    """In-process executor (dev fallback); RunnerError/PatchError keep today's mapping."""
    from evoforge import runner
    from evoforge.patch import PatchError
    try:
        return runner.run_candidate(source_repo, base_sha, diff,
                                    tests, normalized,
                                    timeout_s=timeout_s)
    except runner.RunnerError as e:
        from evoforge import repo_source as _rs
        raise HTTPException(400, _rs.redact(str(e)))
    except PatchError as e:
        raise HTTPException(409, str(e))


def _run_remote(source_repo: str, base_sha: str, diff: str, tests: list,
                normalized: list, timeout_s: int = 120) -> dict:
    """Isolated Runner over HTTP; runner-side trouble is 502, never a local 500."""
    from evoforge import repo_source as _rs2
    from evoforge import runner_client as _rc
    from evoforge.patch import PatchError
    try:
        return _rc.run_via_runner(source_repo, base_sha, diff,
                                  tests, normalized,
                                  timeout_s=timeout_s)
    except _rc.RunnerTooLarge as e:
        raise HTTPException(413, _rs2.redact(str(e)))
    except _rc.RunnerBadRequest as e:
        raise HTTPException(400, _rs2.redact(str(e)))
    except _rc.RunnerConflict as e:
        raise HTTPException(409, str(e))
    except _rc.RunnerClientError as e:
        raise HTTPException(502, str(e))
    except PatchError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        # Any other failure while driving the remote Runner (I/O, git,
        # unexpected payload shapes) is a runner-side problem, never a
        # local 500: the spec maps runner trouble to 502.
        raise HTTPException(502, _rs2.redact(f"runner failed: {type(e).__name__}"))


@app.post("/v1/pr/create")
def pr_create(req: PRRequest):
    eid, pr = _pr_core(
        source_evidence_id=req.evidence_id, title=req.title, body_intro=req.body,
        branch=req.branch or f"evoforge/{uuid.uuid4().hex[:8]}", base=req.base,
        store_extra={})
    return {"pr": pr, "evidence_id": eid, "source_evidence_id": req.evidence_id}


@app.post("/v1/eval/sandbox")
def eval_sandbox(req: SandboxRequest):
    import shutil
    import subprocess
    from evoforge import repo_source, runner
    from evoforge.hygiene_api import run_sandbox
    try:
        resolved = repo_source.resolve_repo_dir(req.source_repo, req.base_sha)
    except Exception as e:
        raise HTTPException(400, repo_source.redact(str(e)))
    is_temp = isinstance(req.source_repo, str) and req.source_repo in ("", "github")
    effective_base = req.base_sha
    if is_temp:
        try:
            _hp = subprocess.run(["git", "rev-parse", "HEAD"], cwd=resolved,
                                 capture_output=True, text=True, timeout=30)
            _head = (_hp.stdout or "").strip()
            if _hp.returncode == 0 and _head:
                effective_base = _head
        except Exception:
            pass
    try:
        try:
            out = run_sandbox(resolved, effective_base, req.future_shas)
        except Exception as e:
            raise HTTPException(400, repo_source.redact(f"sandbox failed: {e}"))
    finally:
        if is_temp:
            try:
                runner._remove_tree(resolved)
            except Exception:
                try:
                    shutil.rmtree(resolved, ignore_errors=True)
                except Exception:
                    pass
    eid = _store_evidence({"sandbox": out})
    return {**out, "evidence_id": eid}


class EvalBaselineRequest(BaseModel):
    suite_version: Literal["v0"] = "v0"
    model: Literal["muse-spark-1.3"] = "muse-spark-1.3"
    family: str | None = None


class EvalPipelineRequest(BaseModel):
    suite_version: Literal["v0"] = "v0"
    model: Literal["muse-spark-1.3"] = "muse-spark-1.3"
    family: str | None = None


def _eval_budget_or_402(n_tasks: int, attempts: int, per_attempt: int) -> None:
    try:
        performance_mod.check_budget(n_tasks, attempts, per_attempt)
    except performance_mod.BudgetExceeded as e:
        raise HTTPException(402, str(e))
    except ledger.Overdraft as e:
        raise HTTPException(402, "budget exhausted (reserve_cost refused)")


def _production_stats() -> dict:
    runs = 0
    gate_pass = 0
    gate_fail = 0
    gate_inconclusive = 0
    held_pass = 0
    held_n = 0
    try:
        keys = list(_evidence)
    except Exception:
        keys = []
    for key in keys:
        try:
            stored = _evidence.get(key, {})
        except Exception:
            continue
        if not isinstance(stored, dict) or not isinstance(stored.get("run"), dict):
            continue
        run = stored["run"]
        runs += 1
        gates = stored.get("gates")
        if isinstance(gates, list) and gates:
            results = [g.get("result") for g in gates if isinstance(g, dict)]
            if results and all(r == "PASS" for r in results):
                gate_pass += 1
            elif any(r == "FAIL" for r in results):
                gate_fail += 1
            else:
                gate_inconclusive += 1
        else:
            gate_inconclusive += 1
        held = run.get("heldout")
        if isinstance(held, dict):
            p = held.get("pass")
            nn = held.get("n")
            if isinstance(p, int) and isinstance(nn, int) and nn > 0:
                held_pass += p
                held_n += nn
    pct = (100.0 * held_pass / held_n) if held_n else None
    return {"runs": runs, "gate_pass": gate_pass, "gate_fail": gate_fail,
            "gate_inconclusive": gate_inconclusive,
            "heldout_pass_rate_pct": pct,
            "sample_note": f"operational samples from /v1/runs (n={runs}); "
                           "not a controlled eval"}


@app.get("/v1/eval/suites")
def eval_suites():
    """Redacted sealed v0 catalogue: families plus sha256/len metadata only."""
    from evoforge import repo_source as _rs_eval

    try:
        suites = sealed_eval_mod.public_suites()
    except Exception as e:
        raise HTTPException(
            502, _rs_eval.redact(f"sealed suites unavailable: {type(e).__name__}"))
    return {"suite_version": sealed_eval_mod.SUITE_VERSION, "suites": suites}


@app.post("/v1/eval/baseline", status_code=201)
def eval_baseline(req: EvalBaselineRequest):
    """X_SINGLE baseline over the sealed v0 set in hygiene sandboxes.

    Runner-side trouble maps to 413/502/504 with a short message; a raw
    traceback never leaves the server.
    """
    from evoforge import repo_source as _rs_eval2

    try:
        n_tasks = sealed_eval_mod.count_tasks(req.family)
    except ValueError as e:
        raise HTTPException(400, _rs_eval2.redact(str(e)))
    except sealed_eval_mod.SealedEvalError as e:
        raise HTTPException(502, _rs_eval2.redact(str(e) or "sealed baseline failed"))
    _eval_budget_or_402(n_tasks, 1, sealed_eval_mod.BASELINE_COST_CENTS)
    try:
        result = sealed_eval_mod.run_baseline(
            req.suite_version, req.model, family=req.family)
    except sealed_eval_mod.SealedTooLarge as e:
        raise HTTPException(413, _rs_eval2.redact(str(e)))
    except sealed_eval_mod.SealedTimeout:
        raise HTTPException(504, "sealed baseline timed out")
    except ledger.Overdraft:
        raise HTTPException(402, "budget exhausted (reserve_cost refused)")
    except sealed_eval_mod.SealedEvalError as e:
        raise HTTPException(502, _rs_eval2.redact(str(e) or "sealed baseline failed"))
    except ValueError as e:
        raise HTTPException(400, _rs_eval2.redact(str(e)))
    except HTTPException:
        raise
    except Exception as e:
        name = type(e).__name__
        if isinstance(e, TimeoutError) or "timeout" in name.lower():
            raise HTTPException(504, "sealed baseline timed out")
        raise HTTPException(502, _rs_eval2.redact(f"sealed baseline failed: {name}"))
    xs = result["X_SINGLE"]
    passed = sum(1 for s in result["scores"] if s["score"] >= 1.0)
    gates = [{"gate": "G2_REQUIRED",
              "result": "PASS" if (xs["n"] > 0 and passed == xs["n"]) else "FAIL",
              "reason": f"sealed v0 X_SINGLE executed {passed}/{xs['n']} held-out tasks"}]
    eid = _store_evidence({"baseline_id": result["baseline_id"],
                           "suite_version": result["suite_version"],
                           "model": result["model"], "X_SINGLE": xs,
                           "scaffold": result["scaffold"], "audit": result["audit"],
                           "scores": result["scores"], "tasks": result["tasks"],
                           "by_family": result["by_family"],
                           "reservation_ids": result["reservation_ids"],
                           "reservation_id": result["reservation_id"],
                           "provider_stub": result["provider_stub"],
                           "gates": gates})
    _link_stages(eid, ("Gate", "Outcome"))
    lo, hi = result.get("pass_rate_wilson_lb", 0.0), 1.0
    try:
        import sys as _sys
        import os as _os
        _ref = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..",
                                              "..", "docs", "evoforge-v4.2",
                                              "reference_impl"))
        if _ref not in _sys.path:
            _sys.path.insert(0, _ref)
        import quality_gate as _qg
        lo, hi = _qg.wilson(passed, xs["n"])
    except Exception:
        pass
    per_family = {fam: {"n": v.get("n", 0), "passed": v.get("passed", 0)}
                  for fam, v in result["by_family"].items()}
    measurement = performance_mod.make_record(
        kind="X_SINGLE", suite_version=result["suite_version"],
        model=result["model"],
        harness_version=sealed_eval_mod.HARNESS_VERSION,
        n=xs["n"], passed=passed, cost_cents=xs["cost_cents"],
        per_family=per_family, evidence_id=eid)
    measurement["wilson95"] = [lo, hi]
    measurement["provider_stub"] = result["provider_stub"]
    performance_mod.record(measurement)
    return {"baseline_id": result["baseline_id"], "evidence_id": eid,
            "measurement_id": measurement["measurement_id"],
            "measurement": dict(measurement),
            "suite_version": result["suite_version"], "model": result["model"],
            "X_SINGLE": xs, "audit": result["audit"], "scores": result["scores"],
            "tasks": result["tasks"], "by_family": result["by_family"],
            "chain": evidence_chain.chain(eid)}


@app.post("/v1/eval/pipeline", status_code=201)
def eval_pipeline(req: EvalPipelineRequest):
    """Adaptive pipeline over the sealed v0 set (up to 3 attempts/task).

    Costs are usage-derived per attempt; the total is the sum of all
    settled attempts. No held-out code, reference fix, or task file
    contents ever leave the server.
    """
    from evoforge import repo_source as _rs_eval3

    try:
        n_tasks = sealed_eval_mod.count_tasks(req.family)
    except ValueError as e:
        raise HTTPException(400, _rs_eval3.redact(str(e)))
    except sealed_eval_mod.SealedEvalError as e:
        raise HTTPException(502, _rs_eval3.redact(str(e) or "sealed pipeline failed"))
    _eval_budget_or_402(n_tasks, sealed_eval_mod.PIPELINE_MAX_ATTEMPTS,
                        sealed_eval_mod.PIPELINE_PER_ATTEMPT_MAX_CENTS)
    try:
        result = sealed_eval_mod.run_pipeline(
            req.suite_version, req.model, family=req.family)
    except sealed_eval_mod.SealedTooLarge as e:
        raise HTTPException(413, _rs_eval3.redact(str(e)))
    except sealed_eval_mod.SealedTimeout:
        raise HTTPException(504, "sealed pipeline timed out")
    except ledger.Overdraft:
        raise HTTPException(402, "budget exhausted (reserve_cost refused)")
    except sealed_eval_mod.SealedEvalError as e:
        raise HTTPException(502, _rs_eval3.redact(str(e) or "sealed pipeline failed"))
    except ValueError as e:
        raise HTTPException(400, _rs_eval3.redact(str(e)))
    except HTTPException:
        raise
    except Exception as e:
        name = type(e).__name__
        if isinstance(e, TimeoutError) or "timeout" in name.lower():
            raise HTTPException(504, "sealed pipeline timed out")
        raise HTTPException(502, _rs_eval3.redact(f"sealed pipeline failed: {name}"))
    pipe = result["PIPELINE"]
    passed = sum(1 for s in result["scores"] if s["score"] >= 1.0)
    gates = [{"gate": "G2_REQUIRED",
              "result": "PASS" if (pipe["n"] > 0 and passed == pipe["n"]) else "FAIL",
              "reason": f"sealed v0 PIPELINE executed {passed}/{pipe['n']} held-out tasks"}]
    eid = _store_evidence({"pipeline_id": result["pipeline_id"],
                           "suite_version": result["suite_version"],
                           "model": result["model"], "PIPELINE": pipe,
                           "scaffold": result["scaffold"], "audit": result["audit"],
                           "scores": result["scores"], "tasks": result["tasks"],
                           "by_family": result["by_family"],
                           "reservation_ids": result["reservation_ids"],
                           "reservation_id": result["reservation_id"],
                           "provider_stub": result["provider_stub"],
                           "attempts_total": result["attempts_total"],
                           "usage_missing": result["usage_missing"],
                           "gates": gates})
    _link_stages(eid, ("Gate", "Outcome"))
    per_family = {fam: {"n": v.get("n", 0), "passed": v.get("passed", 0)}
                  for fam, v in result["by_family"].items()}
    measurement = performance_mod.make_record(
        kind="PIPELINE", suite_version=result["suite_version"],
        model=result["model"],
        harness_version=sealed_eval_mod.HARNESS_VERSION,
        n=pipe["n"], passed=passed, cost_cents=pipe["cost_cents"],
        per_family=per_family, evidence_id=eid,
        attempts_total=result["attempts_total"],
        usage_missing=result["usage_missing"])
    measurement["wilson95"] = [result["pass_rate_wilson_lo"],
                               result["pass_rate_wilson_hi"]]
    measurement["provider_stub"] = result["provider_stub"]
    performance_mod.record(measurement)
    return {"pipeline_id": result["pipeline_id"], "evidence_id": eid,
            "measurement_id": measurement["measurement_id"],
            "measurement": dict(measurement),
            "suite_version": result["suite_version"], "model": result["model"],
            "PIPELINE": pipe, "audit": result["audit"],
            "scores": result["scores"], "tasks": result["tasks"],
            "by_family": result["by_family"],
            "attempts_total": result["attempts_total"],
            "usage_missing": result["usage_missing"],
            "chain": evidence_chain.chain(eid)}


@app.get("/v1/performance")
def performance():
    """Measured-only performance summary; missing data is not_measured."""
    baseline = performance_mod.latest("X_SINGLE")
    pipeline = performance_mod.latest("PIPELINE")
    if baseline is None:
        base_view: dict = {"status": "not_measured",
                           "reason": "no X_SINGLE measurement yet",
                           "record": None}
    else:
        base_view = {"status": "measured", "reason": "",
                     "record": dict(baseline), **dict(baseline)}
    if pipeline is None:
        pipe_view: dict = {"status": "not_measured",
                           "reason": "no PIPELINE measurement yet",
                           "record": None}
    else:
        pipe_view = {"status": "measured", "reason": "",
                     "record": dict(pipeline), **dict(pipeline)}
    comparison = performance_mod.compare(baseline, pipeline)
    return {"baseline": base_view, "pipeline": pipe_view,
            "comparison": comparison,
            "cost_per_solved_cents": {
                "baseline": performance_mod.cost_per_solved(baseline),
                "pipeline": performance_mod.cost_per_solved(pipeline)},
            "history": performance_mod.history(),
            "production": _production_stats(),
            "storage": "postgres" if postgres_state.backend() else "memory"}


@app.get("/v1/evidence/{eid}")
def evidence(eid: str):
    if eid not in _evidence:
        raise HTTPException(404, "unknown evidence id")
    stored = _evidence[eid]
    public = _redact_value(stored)
    # Surface sealed metadata at the top level too (mirrors POST shape) so
    # clients need not dig into data/review payloads; counts included.
    inner = public.get("review")
    if isinstance(inner, dict) and isinstance(inner.get("sealed_tests"), list):
        public.setdefault("sealed_tests", inner["sealed_tests"])
        for ck in ("sealed_count", "sealed_tests_count", "sealed_kinds"):
            if ck in inner:
                public.setdefault(ck, inner[ck])
    data = {k: v for k, v in public.items() if k not in ("chain", "data")}
    return {**public, "chain": evidence_chain.chain(eid), "data": data}


@app.get("/v1/events/{event_id}")
def event(event_id: str):
    view = evidence_chain.view(event_id)
    if view is None:
        raise HTTPException(404, "unknown event id")
    return view


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


class MissionCreate(BaseModel):
    goal: str
    repo_ref: str = "HEAD"
    target_paths: list | None = None
    risk: str = "LOW"
    confirm: bool = False


class MissionAdvance(BaseModel):
    to: Literal["GENERATED", "REVIEWED", "RAN", "PR_OPENED", "CANCELLED", "FAILED"]


_HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")


def _resolve_mission_base(repo_ref: str) -> str:
    """Resolve a mission repo_ref to a concrete SHA without the GitHub API.

    Branch/tag/HEAD refs are resolved with `git ls-remote` against the
    configured remote, so missions work offline against a local
    EVO_GITHUB_GIT_BASE and in production without an extra API call; full
    SHAs pass through untouched. The token travels only as an HTTP header
    value via the environment, never in argv or error messages.
    """
    import subprocess

    from evoforge import repo_source as _rs

    ref = repo_ref.strip()
    if _HEX40.match(ref):
        return ref
    try:
        remote = _rs.github_remote()
    except Exception as e:
        raise HTTPException(400, _rs.redact(str(e)))
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
    env["GIT_ASKPASS"] = "false"
    tok = os.getenv("GITHUB_TOKEN", "") or ""
    if tok:
        import base64

        header = "Authorization: Basic " + base64.b64encode(
            f"x-access-token:{tok}".encode("utf-8")).decode("ascii")
        env["GIT_CONFIG_COUNT"] = "2"
        env["GIT_CONFIG_KEY_0"] = "http.extraheader"
        env["GIT_CONFIG_VALUE_0"] = header
        env["GIT_CONFIG_KEY_1"] = "credential.helper"
        env["GIT_CONFIG_VALUE_1"] = ""
    try:
        proc = subprocess.run(["git", "ls-remote", remote, ref],
                              capture_output=True, text=True, timeout=30, env=env)
    except Exception:
        raise HTTPException(400, f"unknown base ref: {ref!r}")
    if proc.returncode != 0:
        raise HTTPException(400, _rs.redact(f"unknown base ref: {ref!r}"))
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) != 2 or not _HEX40.match(parts[0]):
            continue
        if parts[1] in (ref, f"refs/heads/{ref}", f"refs/tags/{ref}"):
            return parts[0]
    raise HTTPException(400, f"unknown base ref: {ref!r}")


def _mission_public(mission: dict) -> dict:
    pr_url = None
    pr_eid = mission["stages"]["pr"]
    if pr_eid:
        pr_ev = _evidence.get(pr_eid, {})
        if isinstance(pr_ev.get("pr"), str):
            pr_url = pr_ev["pr"]
    return {
        "mission_id": mission["mission_id"],
        "state": mission["state"],
        "goal": mission["goal"],
        "repo_ref": mission["repo_ref"],
        "target_paths": mission["target_paths"],
        "risk": mission["risk"],
        "created_at": mission["created_at"],
        "updated_at": mission["updated_at"],
        "evidence_ids": list(mission["evidence_ids"]),
        "generate_evidence_id": mission["stages"]["generate"],
        "review_evidence_id": mission["stages"]["review"],
        "run_evidence_id": mission["stages"]["run"],
        "pr_evidence_id": mission["stages"]["pr"],
        "pr_url": pr_url,
    }


def _mission_step_generate(mission: dict) -> str:
    """Mission GENERATED step: same core as POST /v1/commands/generate."""
    validated = mission["target_paths"] or []
    base_sha = mission["repo_ref"]
    file_context = None
    if validated:
        # Branch refs resolve to a SHA first so context loading and the
        # Builder see the same concrete base the existing helpers expect.
        base_sha = _resolve_mission_base(mission["repo_ref"])
        file_context = _load_builder_context(base_sha, validated)
    eid, _, _ = _generate_core(
        goal=mission["goal"], base_sha=base_sha, file_context=file_context,
        store_extra={"mission_id": mission["mission_id"]})
    return eid


def _mission_step_review(mission: dict) -> str:
    """Mission REVIEWED step: same core as POST /v1/candidates/review."""
    gen_eid = mission["stages"]["generate"]
    gen = _evidence.get(gen_eid, {})
    cand = gen.get("candidate") if isinstance(gen.get("candidate"), dict) else {}
    diff = cand.get("diff") if isinstance(cand.get("diff"), str) else ""
    eid, _, phase_evidence_ids = _review_core(
        goal_contract=mission["goal"], diff=diff, ci="",
        store_extra={"mission_id": mission["mission_id"]})
    for pid in phase_evidence_ids:
        missions_store.attach_evidence(mission["mission_id"], pid)
    return eid


def _mission_step_run(mission: dict) -> str:
    """Mission RAN step: same core as POST /v1/runs, at the configured repo ('')."""
    review_eid = mission["stages"]["review"]
    # Review validity (404/409) precedes base resolution, as in POST /v1/runs.
    _validated_sealed_suite(review_eid)
    gen = _evidence.get(mission["stages"]["generate"], {})
    cand = gen.get("candidate") if isinstance(gen.get("candidate"), dict) else {}
    diff = cand.get("diff") if isinstance(cand.get("diff"), str) else ""
    tests = cand.get("tests") if isinstance(cand.get("tests"), list) else []
    base_sha = mission["repo_ref"]
    if not _HEX40.match(base_sha.strip()):
        base_sha = _resolve_mission_base(base_sha)
    eid, _, _ = _run_core(
        source_repo="", base_sha=base_sha, diff=diff, tests=tests,
        review_evidence_id=review_eid, timeout_s=120,
        store_extra={"mission_id": mission["mission_id"]})
    return eid


def _mission_step_pr(mission: dict) -> str:
    """Mission PR_OPENED step: same core as POST /v1/pr/create."""
    run_eid = mission["stages"]["run"]
    title = f"evoforge mission: {mission['goal'][:80]}"
    eid, _ = _pr_core(
        source_evidence_id=run_eid, title=title, body_intro=mission["goal"],
        branch=f"evoforge/{uuid.uuid4().hex[:8]}", base="main",
        store_extra={"mission_id": mission["mission_id"]})
    return eid


_MISSION_STEPS = {
    "GENERATED": _mission_step_generate,
    "REVIEWED": _mission_step_review,
    "RAN": _mission_step_run,
    "PR_OPENED": _mission_step_pr,
}


@app.post("/v1/missions", status_code=201)
def mission_create(req: MissionCreate):
    if not req.goal.strip():
        raise HTTPException(400, "goal required")
    if not isinstance(req.repo_ref, str) or not req.repo_ref.strip():
        raise HTTPException(400, "repo_ref required")
    validated_paths = None
    if req.target_paths is not None:
        validated_paths = _validate_target_paths(req.target_paths)
    try:
        mission = missions_store.create(req.goal, req.repo_ref, validated_paths,
                                        req.risk, req.confirm)
    except MissionNeedsConfirmation as e:
        raise HTTPException(409, str(e))
    eid = _store_evidence({"mission_id": mission["mission_id"], "goal": req.goal,
                           "risk": req.risk, "repo_ref": req.repo_ref})
    _link_stages(eid, ("ObjectiveVersion",))
    missions_store.attach_evidence(mission["mission_id"], eid)
    return {"mission_id": mission["mission_id"], "state": mission["state"],
            "evidence_id": eid}


@app.get("/v1/missions")
def missions_list():
    return {"missions": [
        {"mission_id": m["mission_id"], "state": m["state"], "goal": m["goal"],
         "updated_at": m["updated_at"], "evidence_ids": list(m["evidence_ids"])}
        for m in missions_store.all()
    ]}


@app.get("/v1/missions/{mission_id}")
def mission_detail(mission_id: str):
    mission = missions_store.get(mission_id)
    if mission is None:
        raise HTTPException(404, "unknown mission")
    return _mission_public(mission)


@app.post("/v1/missions/{mission_id}/advance")
def mission_advance(mission_id: str, req: MissionAdvance):
    mission = missions_store.get(mission_id)
    if mission is None:
        raise HTTPException(404, "unknown mission")
    if req.to not in missions_store.STATES:
        raise HTTPException(400, f"unknown state: {req.to}")
    if mission["state"] in missions_store.TERMINAL:
        raise HTTPException(409, f"mission {mission_id} is terminal ({mission['state']})")
    if req.to not in missions_store.NEXT.get(mission["state"], set()):
        raise HTTPException(409, f"{mission['state']} -> {req.to} illegal")
    if req.to in ("CANCELLED", "FAILED"):
        missions_store.mark(mission_id, req.to)
        return {"mission_id": mission_id, "state": req.to,
                "evidence_ids": list(mission["evidence_ids"])}
    # Forward step: run the existing server-side chain first; the mission only
    # moves when the step succeeds, so a 409/402/502 leaves the state (and the
    # evidence chain) untouched.
    eid = _MISSION_STEPS[req.to](mission)
    missions_store.attach_evidence(mission_id, eid, missions_store.STAGE_OF[req.to])
    missions_store.mark(mission_id, req.to)
    return {"mission_id": mission_id, "state": req.to, "evidence_id": eid,
            "evidence_ids": list(mission["evidence_ids"])}


@app.post("/v1/missions/{mission_id}/cancel")
def mission_cancel(mission_id: str):
    mission = missions_store.get(mission_id)
    if mission is None:
        raise HTTPException(404, "unknown mission")
    if mission["state"] in missions_store.TERMINAL:
        raise HTTPException(409, f"mission {mission_id} is terminal ({mission['state']})")
    # Cancel marks the state only; evidence is never deleted.
    missions_store.mark(mission_id, "CANCELLED")
    return {"mission_id": mission_id, "state": "CANCELLED"}


@app.get("/v1/dashboard")
def dashboard():
    by_state = {s: 0 for s in missions_store.STATES}
    active = 0
    blocked = 0
    for m in missions_store.all():
        by_state[m["state"]] = by_state.get(m["state"], 0) + 1
        if m["state"] not in missions_store.TERMINAL:
            active += 1
        if m["state"] == "FAILED":
            blocked += 1
        elif m["state"] == "RAN":
            run_eid = m["stages"]["run"]
            run_ev = _evidence.get(run_eid, {}) if run_eid else {}
            gates = run_ev.get("gates")
            if isinstance(gates, list) and any(g.get("result") != "PASS" for g in gates
                                               if isinstance(g, dict)):
                blocked += 1
    snap = ledger.snapshot("default")
    validated = _all_validated()
    return {
        "missions_by_state": by_state,
        "active_missions": active,
        "blocked_merges": blocked,
        "validated_improvements": len(validated),
        "validated_mission_ids": [o["mission_id"] for o in validated],
        "spent_cents": snap["spent_cents"],
        "reserved_cents": snap["reserved_cents"],
        "unknown_holds": len(snap["unknown_reservations"]),
    }


@app.get("/v1/participants")
def participants():
    """Return only participants linked by recorded work in the current project."""
    from evoforge.admin_participants import list_participants
    return list_participants()


class OutcomeRequest(BaseModel):
    mission_id: str
    merged_sha: str
    pr_url: str = ""


@app.post("/v1/outcomes", status_code=201)
def outcome_record(req: OutcomeRequest):
    mission = missions_store.get(req.mission_id)
    if mission is None:
        raise HTTPException(404, "unknown mission")
    run_eid = (mission.get("stages") or {}).get("run")
    pr_eid = (mission.get("stages") or {}).get("pr")
    run_ev = _evidence.get(run_eid, {}) if run_eid else {}
    pr_ev = _evidence.get(pr_eid, {}) if pr_eid else {}
    try:
        out = outcomes_store.record(mission, run_ev, pr_ev, req.merged_sha, req.pr_url)
    except KeyError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    eid = _store_evidence({"outcome": out, "mission_id": req.mission_id})
    missions_store.attach_evidence(req.mission_id, eid)
    return {**out, "evidence_id": eid}


@app.get("/v1/outcomes")
def outcomes_list():
    return {"outcomes": _all_validated()}


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


def _all_validated() -> list[dict]:
    """All VALIDATED outcomes: live registry plus recovery from durable
    evidence (survives restarts: the in-memory registry does not)."""
    seen: dict[str, dict] = {}
    for o in outcomes_store.all():
        seen[o["mission_id"]] = o
    try:
        ids = list(_evidence)
    except Exception:
        ids = []
    for eid in ids:
        try:
            doc = _evidence[eid]
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        out = doc.get("outcome")
        if (isinstance(out, dict) and out.get("outcome_status") == "VALIDATED"
                and isinstance(out.get("mission_id"), str)
                and out["mission_id"] not in seen):
            seen[out["mission_id"]] = out
    return list(seen.values())


@app.get("/v1/ledger")
def ledger_snapshot():
    return ledger.snapshot("default")


# ---------------------------------------------------------------------------
# Autonomous Evolution (Autopilot) + Proof Certificates — the new horizon.
# Goal in, verified PR out. Every generation reuses the same trust-kernel
# cores (_generate_core/_review_core/_run_core/_pr_core); nothing here can
# mint a PASS on its own. Certificates carry digests, never code.
# ---------------------------------------------------------------------------
from evoforge import evolution as evo_engine
from evoforge import proof as proof_mod
from evoforge import memory as evo_memory


def _evo_candidate(goal: str, base_sha: str, file_context,
                   store_extra: dict) -> dict:
    """One autopilot candidate: generate -> review -> run (best effort).

    Systemic failures (402 budget, 502 provider) propagate and abort the
    generation. Expected verification failures (stub review, 409 gates)
    are captured as candidate data so evolution can learn from them.
    """
    import hashlib as _hl

    gen_eid, candidate, gen_verdicts = _generate_core(
        goal=goal, base_sha=base_sha, file_context=file_context,
        store_extra={**store_extra, "autopilot": True})
    diff = candidate.get("diff") if isinstance(candidate.get("diff"), str) else ""
    out: dict = {
        "generate_evidence_id": gen_eid,
        "review_evidence_id": None,
        "run_evidence_id": None,
        "gates": [v.__dict__ for v in gen_verdicts],
        "review_result": None,
        "run": None,
        "diff_chars": len(diff),
        "diff_sha256": _hl.sha256(diff.encode("utf-8")).hexdigest(),
        "candidate_error": None,
    }
    try:
        rev_eid, review_out, phase_ids = _review_core(
            goal_contract=goal, diff=diff, ci="",
            store_extra={**store_extra, "autopilot": True})
    except HTTPException as e:
        out["candidate_error"] = f"review: {e.status_code} {e.detail}"
        return out
    out["review_evidence_id"] = rev_eid
    inner = review_out.get("review") if isinstance(review_out, dict) else None
    if isinstance(inner, dict):
        out["review_result"] = inner.get("result")
    if isinstance(review_out, dict) and review_out.get("stub") is True:
        out["candidate_error"] = "review: stub (no MODEL_API_KEY) — cannot back a run"
        return out
    tests = candidate.get("tests") if isinstance(candidate.get("tests"), list) else []
    try:
        run_eid, gates, run = _run_core(
            source_repo="", base_sha=base_sha, diff=diff, tests=tests,
            review_evidence_id=rev_eid, timeout_s=120, store_extra={**store_extra, "autopilot": True})
    except HTTPException as e:
        out["candidate_error"] = f"run: {e.status_code} {e.detail}"
        return out
    out["run_evidence_id"] = run_eid
    out["gates"] = gates
    out["run"] = run
    return out


class EvolutionStart(BaseModel):
    goal: str
    repo_ref: str = "HEAD"
    target_paths: list | None = None
    max_generations: int = 3
    population: int = 2
    use_memory: bool = True


@app.post("/v1/evolution/start", status_code=201)
def evolution_start(req: EvolutionStart):
    if not req.goal.strip():
        raise HTTPException(400, "goal required")
    validated = None
    if req.target_paths is not None:
        validated = _validate_target_paths(req.target_paths)
    try:
        evo = evo_engine.start(req.goal, req.repo_ref, validated,
                               req.max_generations, req.population,
                               req.use_memory)
    except ValueError as e:
        raise HTTPException(400, str(e))
    eid = _store_evidence({"evolution_id": evo["evolution_id"], "goal": req.goal,
                           "repo_ref": req.repo_ref})
    _link_stages(eid, ("ObjectiveVersion",))
    return {"evolution_id": evo["evolution_id"], "evidence_id": eid,
            "status": evo["status"], **evo_engine.public(evo)}


@app.get("/v1/evolution")
def evolution_list():
    return {"evolutions": [evo_engine.public(e) for e in evo_engine.list_all()]}


@app.get("/v1/evolution/{evolution_id}")
def evolution_detail(evolution_id: str):
    evo = evo_engine.get(evolution_id)
    if evo is None:
        raise HTTPException(404, "unknown evolution")
    return evo_engine.public(evo)


@app.post("/v1/evolution/{evolution_id}/step")
def evolution_step(evolution_id: str):
    """Run ONE generation (up to `population` candidates) synchronously."""
    evo = evo_engine.get(evolution_id)
    if evo is None:
        raise HTTPException(404, "unknown evolution")
    if evo["status"] in evo_engine.TERMINAL:
        raise HTTPException(409, f"evolution {evolution_id} is terminal ({evo['status']})")
    base_sha = evo["repo_ref"]
    if not _HEX40.match(base_sha.strip()):
        try:
            base_sha = _resolve_mission_base(base_sha)
        except HTTPException:
            pass  # local/HEAD refs resolve inside the cores; keep original
    file_context = None
    if evo.get("target_paths"):
        try:
            file_context = _load_builder_context(base_sha, evo["target_paths"])
        except HTTPException as e:
            raise e
    goal = evo["goal"]
    if evo.get("use_memory", True):
        hint = evo_memory.hint_block(evo["goal"])
        if hint:
            goal = goal + "\n\n" + hint
    if evo["generations"]:
        goal = evo_engine.feedback_goal(goal, evo["generations"][-1])
    candidates = [_evo_candidate(goal, base_sha, file_context,
                                 {"evolution_id": evolution_id})
                  for _ in range(evo["population"])]
    gen = evo_engine.record_generation(evolution_id, candidates)
    _maybe_memorize(evo_engine.get(evolution_id))
    evo = evo_engine.get(evolution_id)
    assert evo is not None
    return {"evolution_id": evolution_id, "status": evo["status"],
            "generation": gen["index"], "converged": gen["converged"],
            "winner": gen["winner"]}


def _maybe_memorize(evo: dict | None) -> None:
    """Distill converged winners into memory (server-side only, code never hits HTTP)."""
    if not evo or evo.get("status") != "CONVERGED":
        return
    winner = (evo.get("generations") or [{}])[-1].get("winner") or {}
    gen_eid = winner.get("generate_evidence_id")
    diff = ""
    if gen_eid:
        cand = _evidence.get(gen_eid, {}).get("candidate")
        if isinstance(cand, dict) and isinstance(cand.get("diff"), str):
            diff = cand["diff"]
    fit = (winner.get("fitness") or {}).get("score", 0.0)
    try:
        evo_memory.record(evo["evolution_id"], evo["goal"], diff,
                          float(fit), winner.get("run_evidence_id"))
    except Exception:
        pass


@app.post("/v1/evolution/{evolution_id}/run")
def evolution_run(evolution_id: str):
    """Run generations until CONVERGED or EXHAUSTED (bounded by max_generations)."""
    evo = evo_engine.get(evolution_id)
    if evo is None:
        raise HTTPException(404, "unknown evolution")
    ran = 0
    last: dict | None = None
    while evo["status"] == "RUNNING":
        step = evolution_step(evolution_id)
        last = step
        ran += 1
        evo = evo_engine.get(evolution_id)
        assert evo is not None
    return {"evolution_id": evolution_id, "status": evo["status"],
            "generations_ran": ran, "last_generation": (last or {}).get("generation"),
            "best": (evo_engine.public(evo))["best"]}


@app.post("/v1/evolution/{evolution_id}/cancel")
def evolution_cancel(evolution_id: str):
    try:
        evo = evo_engine.cancel(evolution_id)
    except KeyError:
        raise HTTPException(404, "unknown evolution")
    return {"evolution_id": evolution_id, "status": evo["status"]}


@app.post("/v1/evolution/{evolution_id}/promote", status_code=201)
def evolution_promote(evolution_id: str):
    """Open a PR from the best CONVERGED run. Non-PASS best is 409 — no exceptions."""
    evo = evo_engine.get(evolution_id)
    if evo is None:
        raise HTTPException(404, "unknown evolution")
    best = (evo.get("best") or {})
    run_eid = best.get("run_evidence_id")
    if not run_eid:
        raise HTTPException(409, "no verified run to promote yet — evolve first")
    title = f"evoforge autopilot: {evo['goal'][:80]}"
    eid, pr = _pr_core(source_evidence_id=run_eid, title=title,
                        body_intro=f"Autopilot {evolution_id} gen {best.get('generation')}: {evo['goal']}",
                        branch=f"evoforge/evo-{uuid.uuid4().hex[:8]}", base="main",
                        store_extra={"evolution_id": evolution_id})
    return {"pr": pr, "evidence_id": eid, "source_evidence_id": run_eid}


@app.get("/v1/proof/{evidence_id}")
def proof_certificate(evidence_id: str):
    """Public proof certificate over redacted evidence: digests, never code."""
    if evidence_id not in _evidence:
        raise HTTPException(404, "unknown evidence id")
    stored = _evidence[evidence_id]
    public_view = _redact_value(stored)
    data = {k: v for k, v in public_view.items() if k not in ("chain", "data")}
    diff = stored.get("diff") if isinstance(stored.get("diff"), str) else ""
    if diff and not data.get("diff_sha256"):
        import hashlib as _hl2
        data["diff_sha256"] = _hl2.sha256(diff.encode("utf-8")).hexdigest()
    cand = stored.get("candidate") if isinstance(stored.get("candidate"), dict) else {}
    if isinstance(cand.get("diff"), str) and not data.get("diff_sha256"):
        import hashlib as _hl3
        data["diff_sha256"] = _hl3.sha256(cand["diff"].encode("utf-8")).hexdigest()
    cert = proof_mod.mint(evidence_id, data, evidence_chain.chain(evidence_id))
    return {**cert, "verify": proof_mod.verify(cert)}


@app.get("/v1/leaderboard")
def leaderboard():
    """Trust leaderboard: converged evolutions ranked by fitness, then speed.

    The unit of prestige is a VERIFIED fix with a proof link — not a claim.
    """
    rows = []
    for e in evo_engine.list_all():
        if e.get("status") != "CONVERGED" or not e.get("best"):
            continue
        best = e["best"]
        fit = best.get("fitness") or {}
        run_eid = best.get("run_evidence_id")
        rows.append({
            "evolution_id": e["evolution_id"],
            "goal": e["goal"],
            "generations_used": len(e.get("generations", [])),
            "best_score": fit.get("score", 0.0),
            "proof_evidence_id": run_eid,
            "proof_path": f"/v1/proof/{run_eid}" if run_eid else None,
        })
    rows.sort(key=lambda r: (-(r["best_score"] or 0.0), r["generations_used"]))
    return {"leaders": rows, "count": len(rows)}


@app.get("/v1/memory")
def memory_list():
    """Digest-only view of what the factory has learned. No code, ever."""
    return {"patterns": evo_memory.public_all(), "count": len(evo_memory.public_all())}
