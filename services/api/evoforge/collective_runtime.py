"""5-Seat Adaptive Collective, 12-Tool MCP Surface, Compaction Boundary Collector, and M6 Harness Optimizer Runtime.

Integrates the executable specifications in `docs/evoforge-v4.2/reference_impl/` and schemas in
`docs/evoforge-v4.2/contracts/` into the `services/api/evoforge` runtime:
  * CR-59: Agent onboarding & credential state gate (`AUTHORIZED` + `READY` + `VALID`/`EXPIRING`).
  * CR-60: Atomic task claim, lease expiration reclaim, and `lease_epoch` fencing (`STALE_WRITE`).
  * CR-61 & CR-71: Wave composition gate (`GC_COMPOSITION`), minimal culprit pair attribution,
    and AST-based interface-change notices (`notices_from_sources`) pushed to referencing Builders.
  * CR-65: Prediction-Powered Inference (`ppi.noninferiority`) for human acceptance labels, blocked on safety metrics.
  * CR-70: Cohesion-aware graph partitioning (`partitioner.plan`) choosing `DAG_PARALLEL` vs `SINGLE`.
  * CR-72: Execution-evidence-first candidate selection (`selection.select`) and adaptive-k early stopping.
  * CR-73: Read-only speculative execution (`speculative.run`), isotonic model cascade (`cascade`),
    and phase-gated experience memory (`memory_policy`).
  * CR-75: Reversible epoch folding (`ReFold`) at explicit epoch boundaries + paired 3-turn continuation
    collector and `compaction_eval.decide` gate.
  * CR-76: M6 Harness Optimizer runtime loop (`harness-patch/v1` schema validation, deterministic patch
    application, EvoDAG lineage, `GEPA` baseline, `120 -> 20` edit-budget annealing, Trust Kernel protection,
    `OPEN -> FROZEN -> CLOSED` state machine).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Callable

from jsonschema import Draft202012Validator

_REPO_ROOT = Path(__file__).resolve().parents[3]
_V42_ROOT = _REPO_ROOT / "docs" / "evoforge-v4.2"
_REF_IMPL = _V42_ROOT / "reference_impl"
if str(_REF_IMPL) not in sys.path:
    sys.path.insert(0, str(_REF_IMPL))

import cascade as ref_cascade  # noqa: E402
import compaction_eval as ref_compaction_eval  # noqa: E402
import composition_gate as ref_composition_gate  # noqa: E402
import harness_optimizer as ref_harness_optimizer  # noqa: E402
import memory_policy as ref_memory_policy  # noqa: E402
import partitioner as ref_partitioner  # noqa: E402
import ppi as ref_ppi  # noqa: E402
import quality_gate as ref_quality_gate  # noqa: E402
import selection as ref_selection  # noqa: E402
import speculative as ref_speculative  # noqa: E402


@lru_cache(maxsize=1)
def _load_vocabulary() -> dict:
    vocab_path = _V42_ROOT / "contracts" / "vocabulary.json"
    return json.loads(vocab_path.read_text(encoding="utf-8"))["canonical"]


@lru_cache(maxsize=1)
def _load_gates() -> dict:
    gates_path = _V42_ROOT / "contracts" / "quality_gates.json"
    return json.loads(gates_path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _harness_patch_validator() -> Draft202012Validator:
    schema_path = _V42_ROOT / "contracts" / "schemas" / "harness-patch.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


CANONICAL_SEAT_LABELS: tuple[str, ...] = tuple(_load_vocabulary()["seat_label"])
CANONICAL_FUNCTION_ROLES: tuple[str, ...] = tuple(_load_vocabulary()["function_role"])
CANONICAL_MCP_TOOLS: tuple[str, ...] = tuple(_load_vocabulary()["mcp_tools"])


class CollectiveRuntimeError(RuntimeError):
    """Base error for collective runtime violations."""


class AgentAccessDeniedError(CollectiveRuntimeError):
    """Raised when an agent is not authorized/ready or has an expired/revoked credential (CR-59)."""


class ClaimLostError(CollectiveRuntimeError):
    """Raised when a task cannot be claimed because another active lease holds it (CR-60)."""


class StaleWriteError(CollectiveRuntimeError):
    """Raised when an agent attempts a write with an outdated lease_epoch or expired lease (CR-60)."""


class CompactionPolicyError(CollectiveRuntimeError):
    """Raised when epoch folding violates Context Mesh §7.1 rules (CR-75)."""


# ==============================================================================
# 1. Compaction Boundary Continuation Collector & Reversible Epoch Folding (CR-75)
# ==============================================================================


@dataclass(frozen=True)
class ContinuationTurnTrace:
    """Single continuation turn trace after a compaction boundary."""

    turn_index: int
    succeeded: bool
    repeated_explorations: int = 0
    blocked_actions: int = 0


@dataclass(frozen=True)
class FoldedContextItem:
    item_id: str
    layer: str
    epoch: int
    fidelity: str
    requires_original: bool
    content: str
    ref: str | None = None
    sha256: str | None = None
    byte_length: int | None = None
    one_line_summary: str | None = None


class CompactionBoundaryRuntime:
    """Reversible epoch compaction (`ReFold`) + boundary-local continuation evaluator (`CR-75`)."""

    def __init__(self, gates: dict | None = None) -> None:
        self.gates = gates or _load_gates()
        self._boundaries: list[ref_compaction_eval.Boundary] = []

    def fold_epoch_items(
        self,
        items: list[dict],
        *,
        current_epoch: int,
        at_epoch_boundary: bool,
    ) -> list[FoldedContextItem]:
        """Fold completed prior-epoch `L3_TASK_DELTA` items into `REF_ONLY` stubs at an epoch boundary.

        Rules (Context_Mesh_Spec.md §7.1):
          1. Folding is permitted ONLY at an explicit epoch boundary (`at_epoch_boundary=True`).
          2. `L0_PLATFORM`, `L1_TENANT_CONTRACT`, `L2_ROLE_SCOPE`, and any item with `requires_original=True`
             are never folded to `REF_ONLY`.
          3. Every folded `REF_ONLY` item MUST carry a valid Vault `ref`, `sha256`, `byte_length`, and
             `one_line_summary` so `retrieve_evidence` can losslessly restore the original bytes.
        """
        if not at_epoch_boundary:
            raise CompactionPolicyError("epoch folding is only allowed at explicit epoch boundaries")
        if current_epoch < 1:
            raise CompactionPolicyError("current_epoch must be >= 1 to fold prior epochs")

        out: list[FoldedContextItem] = []
        for raw in items:
            item_id = raw["item_id"]
            layer = raw["layer"]
            epoch = int(raw.get("epoch", current_epoch))
            requires_original = bool(raw.get("requires_original", False))
            content = raw.get("content", "")
            ref = raw.get("ref")

            if (
                epoch < current_epoch
                and layer == "L3_TASK_DELTA"
                and not requires_original
            ):
                if not isinstance(ref, str) or not ref.startswith("ev_"):
                    raise CompactionPolicyError(
                        f"cannot fold item {item_id} to REF_ONLY without a valid Vault ref"
                    )
                raw_bytes = content.encode("utf-8")
                digest = raw.get("sha256") or hashlib.sha256(raw_bytes).hexdigest()
                byte_len = raw.get("byte_length") if raw.get("byte_length") is not None else len(raw_bytes)
                first_line = next((ln.strip() for ln in content.splitlines() if ln.strip()), "folded epoch evidence")
                summary = raw.get("one_line_summary") or first_line[:160]
                out.append(
                    FoldedContextItem(
                        item_id=item_id,
                        layer=layer,
                        epoch=epoch,
                        fidelity="REF_ONLY",
                        requires_original=False,
                        content=f"[REF_ONLY ref={ref} sha256={digest[:12]} bytes={byte_len}] {summary}",
                        ref=ref,
                        sha256=digest,
                        byte_length=int(byte_len),
                        one_line_summary=summary,
                    )
                )
            else:
                out.append(
                    FoldedContextItem(
                        item_id=item_id,
                        layer=layer,
                        epoch=epoch,
                        fidelity=raw.get("fidelity", "RAW"),
                        requires_original=requires_original,
                        content=content,
                        ref=ref,
                        sha256=raw.get("sha256"),
                        byte_length=raw.get("byte_length"),
                        one_line_summary=raw.get("one_line_summary"),
                    )
                )
        return out

    def record_paired_continuation(
        self,
        *,
        session_id: str,
        boundary_id: str,
        baseline_seed_runs: list[list[ContinuationTurnTrace]],
        candidate_seed_runs: list[list[ContinuationTurnTrace]],
    ) -> ref_compaction_eval.Boundary:
        """Record paired N-turn continuations (uncompacted baseline vs compacted candidate) from one boundary."""
        max_turns = int(self.gates["compaction_eval"]["continuation_turns"])
        if not baseline_seed_runs or len(baseline_seed_runs) != len(candidate_seed_runs):
            raise ValueError("baseline_seed_runs and candidate_seed_runs must be non-empty and paired by seed")

        base_success: list[int] = []
        cand_success: list[int] = []
        base_repeats_total = 0.0
        cand_repeats_total = 0.0
        base_blocked_total = 0.0
        cand_blocked_total = 0.0

        for b_turns, c_turns in zip(baseline_seed_runs, candidate_seed_runs):
            b_window = b_turns[:max_turns]
            c_window = c_turns[:max_turns]
            base_success.append(1 if any(t.succeeded for t in b_window) else 0)
            cand_success.append(1 if any(t.succeeded for t in c_window) else 0)
            base_repeats_total += sum(t.repeated_explorations for t in b_window)
            cand_repeats_total += sum(t.repeated_explorations for t in c_window)
            base_blocked_total += sum(t.blocked_actions for t in b_window)
            cand_blocked_total += sum(t.blocked_actions for t in c_window)

        n_seeds = len(baseline_seed_runs)
        boundary = ref_compaction_eval.Boundary(
            session_id=session_id,
            boundary_id=boundary_id,
            base_success=base_success,
            cand_success=cand_success,
            base_repeats=base_repeats_total / n_seeds,
            cand_repeats=cand_repeats_total / n_seeds,
            base_blocked=base_blocked_total / n_seeds,
            cand_blocked=cand_blocked_total / n_seeds,
        )
        self._boundaries.append(boundary)
        return boundary

    def add_boundary(self, boundary: ref_compaction_eval.Boundary) -> None:
        self._boundaries.append(boundary)

    def evaluate(self, tier: str = "A_canary") -> dict:
        """Evaluate all collected compaction boundaries against `compaction_eval.decide` (`CR-75`)."""
        return ref_compaction_eval.decide(list(self._boundaries), tier, self.gates)

    @property
    def boundaries(self) -> list[ref_compaction_eval.Boundary]:
        return list(self._boundaries)


# ==============================================================================
# 2. M6 Harness Optimizer Runtime Loop (CR-76)
# ==============================================================================


@dataclass(frozen=True)
class HarnessSnapshot:
    version_id: str
    parent_versions: tuple[str, ...]
    generation: int
    files: dict[str, str]
    patch_id: str | None = None
    minibatch_score: float | None = None
    dev_score: float | None = None


class HarnessOptimizerRuntime:
    """Runtime execution loop for M6 Harness Evolution (`CR-76`, D-051).

    Wraps `reference_impl/harness_optimizer.py` and `harness-patch.v1.schema.json`:
      - Validates every patch against `harness-patch.v1.schema.json` (blocking `evaluated_on=["test"]`,
        path traversal, invalid IDs).
      - Enforces `GEPA` baseline, Trust Kernel protected-glob immunity, and `120 -> 20` edit-budget annealing.
      - Applies structured ops (`insert_after`, `insert_before`, `replace`, `delete`, `create`) to harness files
        and tracks EvoDAG multi-parent lineage.
      - Enforces `OPEN -> FROZEN -> CLOSED` state machine where `D_test` is opened once after freeze.
    """

    def __init__(
        self,
        run_id: str,
        initial_files: dict[str, str],
        *,
        baseline: str = "GEPA",
        initial_version_id: str = "hv_00000001",
        total_generations: int = 11,
        cfg: dict | None = None,
    ) -> None:
        self.cfg = cfg or _load_gates()["optimizer"]
        self.total_generations = total_generations
        self.core_run = ref_harness_optimizer.OptimizationRun(run_id, baseline=baseline, cfg=self.cfg)
        self.versions: dict[str, HarnessSnapshot] = {
            initial_version_id: HarnessSnapshot(
                version_id=initial_version_id,
                parent_versions=(),
                generation=0,
                files=dict(initial_files),
            )
        }
        self.rejected_patches: list[tuple[str, str]] = []

    @property
    def state(self) -> str:
        return self.core_run.state

    @staticmethod
    def validate_patch_schema(patch: dict) -> None:
        err = next(_harness_patch_validator().iter_errors(patch), None)
        if err is not None:
            loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
            raise ref_harness_optimizer.OptimizerError(f"invalid harness-patch/v1 schema at {loc}: {err.message}")

    @staticmethod
    def apply_patch_to_files(files: dict[str, str], patch: dict) -> dict[str, str]:
        """Deterministically apply structured `harness-patch/v1` operations to a copy of `files`."""
        updated = dict(files)
        for op in patch["ops"]:
            path = op["file"]
            kind = op["op"]
            if kind == "create":
                updated[path] = op["text"]
                continue
            src = updated[path]
            anchor = op["anchor"]
            idx = src.find(anchor)
            if idx < 0:
                raise ref_harness_optimizer.OptimizerError(f"anchor not found in {path}")
            if kind == "insert_after":
                pos = idx + len(anchor)
                updated[path] = src[:pos] + op["text"] + src[pos:]
            elif kind == "insert_before":
                updated[path] = src[:idx] + op["text"] + src[idx:]
            elif kind in ("replace", "delete"):
                n_lines = int(op["lines"])
                tail = src[idx:]
                tail_lines = tail.splitlines(keepends=True)
                consumed = "".join(tail_lines[:n_lines])
                replacement = op["text"] if kind == "replace" else ""
                updated[path] = src[:idx] + replacement + src[idx + len(consumed) :]
            else:
                raise ref_harness_optimizer.OptimizerError(f"unsupported op {kind}")
        return updated

    def propose_and_apply(
        self,
        *,
        candidate_version_id: str,
        patch: dict,
        parent_minibatch: float,
        child_minibatch: float,
    ) -> tuple[bool, HarnessSnapshot | None]:
        """Validate, check edit budget & Trust Kernel globs, and if improving on mini-batch, register new version."""
        self.validate_patch_schema(patch)
        parents = tuple(patch["parent_versions"])
        for pid in parents:
            if pid not in self.versions:
                raise ref_harness_optimizer.OptimizerError(f"unknown parent harness version {pid}")
        base_files = dict(self.versions[parents[0]].files)
        generation = int(patch["generation"])
        accepted = self.core_run.propose(
            candidate_version_id,
            patch,
            parent_minibatch,
            child_minibatch,
            generation,
            self.total_generations,
            base_files,
        )
        if not accepted:
            self.rejected_patches.append((patch["patch_id"], "minibatch did not improve"))
            return False, None

        new_files = self.apply_patch_to_files(base_files, patch)
        snap = HarnessSnapshot(
            version_id=candidate_version_id,
            parent_versions=parents,
            generation=generation,
            files=new_files,
            patch_id=patch["patch_id"],
            minibatch_score=child_minibatch,
        )
        self.versions[candidate_version_id] = snap
        return True, snap

    def evaluate_dev(self, version_id: str, score: float) -> None:
        if version_id not in self.versions:
            raise ref_harness_optimizer.OptimizerError(f"unknown candidate version {version_id}")
        self.core_run.record_dev(version_id, score)
        cur = self.versions[version_id]
        self.versions[version_id] = HarnessSnapshot(**{**cur.__dict__, "dev_score": score})

    def select_best_dev(self) -> str:
        return self.core_run.select()

    def freeze_winner(self, version_id: str, dev_pairs_vs_gepa: list[tuple[str, int, int]]) -> str:
        self.core_run.freeze(version_id, dev_pairs_vs_gepa)
        return version_id

    def evaluate_test_once(self, version_id: str, test_score: float) -> dict:
        score = self.core_run.evaluate_test(version_id, test_score)
        return {
            "run_id": self.core_run.run_id,
            "frozen_version_id": self.core_run.frozen,
            "state": self.core_run.state,
            "d_test_score": score,
        }


# ==============================================================================
# 3. 5-Seat Adaptive Collective & 12-Tool MCP Surface (CR-59/60/61/65/70/71/72/73)
# ==============================================================================


@dataclass
class CollectiveAgent:
    tenant_id: str
    agent_id: str
    seat_label: str
    function_role: str
    agent_kind: str = "mcp_chat"
    join_state: str = "AUTHORIZED"
    connection_state: str = "READY"
    execution_state: str = "IDLE"
    credential_state: str = "VALID"


@dataclass
class CollectiveTask:
    tenant_id: str
    project_id: str
    task_id: str
    run_id: str
    risk_level: str
    status: str = "READY"
    version: int = 0
    lease_holder: str | None = None
    lease_epoch: int = 0
    lease_expires_at: float | None = None
    base_sha: str = "0" * 40


class AdaptiveCollectiveCoordinator:
    """5-Seat Adaptive Collective & 12-Tool MCP Coordinator.

    Implements:
      - All 12 canonical MCP tools (`CANONICAL_MCP_TOOLS`).
      - 5-seat registration (`Navigator`, `Builder Alpha`, `Builder Beta`, `Critic`, `Integrator`).
      - Agent onboarding & credential enforcement (`CR-59`).
      - Atomic task claim, lease expiry reclaim, and `lease_epoch` write fencing (`CR-60`).
      - Cohesion-aware task partitioning (`CR-70`), wave composition gate + AST symbol notices (`CR-61`, `CR-71`),
        execution-evidence candidate selection + adaptive-k (`CR-72`), read-only speculation + isotonic cascade +
        phase-gated memory (`CR-73`), and PPI human acceptance non-inferiority (`CR-65`).
    """

    def __init__(self, tenant_id: str, project_id: str) -> None:
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.agents: dict[str, CollectiveAgent] = {}
        self.tasks: dict[str, CollectiveTask] = {}
        self.messages: list[dict] = []
        self.proposals: list[dict] = []
        self.reviews: list[dict] = []
        self.acknowledgements: list[dict] = []
        self.task_contexts: dict[str, dict] = {}
        self.evidence_store: dict[str, bytes] = {}
        self.memory_store: list[ref_memory_policy.Lesson] = []

    # ------------------------------------------------------------------ CR-59 & CR-60 guards
    def agent_can_work(self, agent_id: str) -> bool:
        a = self.agents.get(agent_id)
        if a is None or a.tenant_id != self.tenant_id:
            return False
        return (
            a.join_state == "AUTHORIZED"
            and a.connection_state == "READY"
            and a.credential_state in ("VALID", "EXPIRING")
        )

    def _assert_agent_can_work(self, agent_id: str) -> CollectiveAgent:
        if not self.agent_can_work(agent_id):
            raise AgentAccessDeniedError(f"agent {agent_id} not authorized/ready or credential expired/revoked")
        return self.agents[agent_id]

    def register_task(
        self,
        task_id: str,
        run_id: str,
        risk_level: str = "MEDIUM",
        *,
        base_sha: str = "0" * 40,
        context_packet: dict | None = None,
    ) -> CollectiveTask:
        if risk_level not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            raise ValueError(f"invalid risk_level: {risk_level}")
        t = CollectiveTask(
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            task_id=task_id,
            run_id=run_id,
            risk_level=risk_level,
            base_sha=base_sha,
        )
        self.tasks[task_id] = t
        if context_packet is not None:
            self.task_contexts[task_id] = context_packet
        return t

    def assert_fencing(self, task_id: str, agent_id: str, lease_epoch: int, *, now: float | None = None) -> None:
        now_ts = time.time() if now is None else now
        t = self.tasks.get(task_id)
        if (
            t is None
            or t.lease_holder != agent_id
            or t.lease_epoch != lease_epoch
            or t.lease_expires_at is None
            or t.lease_expires_at < now_ts
        ):
            cur_holder = None if t is None else t.lease_holder
            cur_epoch = None if t is None else t.lease_epoch
            raise StaleWriteError(
                f"STALE_WRITE task {task_id} epoch {lease_epoch} (current holder {cur_holder}, epoch {cur_epoch})"
            )

    # ------------------------------------------------------------------ 12 canonical MCP tools
    def invoke_mcp_tool(self, tool_name: str, **kwargs) -> dict:
        if tool_name not in CANONICAL_MCP_TOOLS:
            raise CollectiveRuntimeError(f"unknown MCP tool: {tool_name}")
        handler = getattr(self, f"mcp_{tool_name}")
        return handler(**kwargs)

    def mcp_join_collective(
        self,
        *,
        agent_id: str,
        seat_label: str,
        function_role: str,
        agent_kind: str = "mcp_chat",
        join_state: str = "AUTHORIZED",
        connection_state: str = "READY",
        credential_state: str = "VALID",
    ) -> dict:
        if seat_label not in CANONICAL_SEAT_LABELS:
            raise ValueError(f"invalid seat_label: {seat_label}")
        if function_role not in CANONICAL_FUNCTION_ROLES:
            raise ValueError(f"invalid function_role: {function_role}")
        agent = CollectiveAgent(
            tenant_id=self.tenant_id,
            agent_id=agent_id,
            seat_label=seat_label,
            function_role=function_role,
            agent_kind=agent_kind,
            join_state=join_state,
            connection_state=connection_state,
            credential_state=credential_state,
        )
        self.agents[agent_id] = agent
        return {"agent_id": agent_id, "seat_label": seat_label, "join_state": join_state}

    def mcp_get_my_tasks(self, *, agent_id: str) -> dict:
        self._assert_agent_can_work(agent_id)
        tasks = [
            {"task_id": t.task_id, "status": t.status, "lease_epoch": t.lease_epoch, "lease_holder": t.lease_holder}
            for t in self.tasks.values()
            if t.status == "READY" or t.lease_holder == agent_id
        ]
        return {"agent_id": agent_id, "tasks": tasks}

    def mcp_claim_task(
        self,
        *,
        agent_id: str,
        task_id: str,
        ttl_seconds: float = 300.0,
        now: float | None = None,
    ) -> dict:
        self._assert_agent_can_work(agent_id)
        now_ts = time.time() if now is None else now
        t = self.tasks.get(task_id)
        if t is None:
            raise KeyError(f"unknown task {task_id}")
        expired = t.status == "CLAIMED" and t.lease_expires_at is not None and t.lease_expires_at < now_ts
        if t.status != "READY" and not expired:
            raise ClaimLostError(f"CLAIM_LOST on task {task_id}")
        t.status = "CLAIMED"
        t.lease_holder = agent_id
        t.lease_epoch += 1
        t.lease_expires_at = now_ts + ttl_seconds
        t.version += 1
        self.agents[agent_id].execution_state = "ASSIGNED"
        return {"task_id": task_id, "agent_id": agent_id, "lease_epoch": t.lease_epoch}

    def mcp_post_message(self, *, agent_id: str, channel: str, body: str) -> dict:
        self._assert_agent_can_work(agent_id)
        msg = {"agent_id": agent_id, "channel": channel, "body": body, "ts": time.time()}
        self.messages.append(msg)
        return msg

    def mcp_submit_proposal(
        self,
        *,
        agent_id: str,
        task_id: str,
        lease_epoch: int,
        candidate_id: str,
        diff: str,
        now: float | None = None,
    ) -> dict:
        self._assert_agent_can_work(agent_id)
        self.assert_fencing(task_id, agent_id, lease_epoch, now=now)
        prop = {
            "candidate_id": candidate_id,
            "task_id": task_id,
            "author_agent_id": agent_id,
            "lease_epoch": lease_epoch,
            "diff": diff,
        }
        self.proposals.append(prop)
        return prop

    def mcp_submit_review(
        self,
        *,
        agent_id: str,
        candidate_id: str,
        verdict: str,
        evidence_kind: str | None = None,
        evidence_ref: str | None = None,
    ) -> dict:
        self._assert_agent_can_work(agent_id)
        prop = next((p for p in self.proposals if p["candidate_id"] == candidate_id), None)
        if prop is not None and prop["author_agent_id"] == agent_id:
            raise CollectiveRuntimeError("author cannot review own candidate")
        if verdict in ("changes_requested", "reject") and (not evidence_kind or not evidence_ref):
            raise CollectiveRuntimeError("blocking review requires evidence_kind and evidence_ref")
        rev = {
            "candidate_id": candidate_id,
            "reviewer_agent_id": agent_id,
            "verdict": verdict,
            "evidence_kind": evidence_kind,
            "evidence_ref": evidence_ref,
        }
        self.reviews.append(rev)
        return rev

    def mcp_acknowledge(self, *, agent_id: str, notice_id: str) -> dict:
        self._assert_agent_can_work(agent_id)
        ack = {"agent_id": agent_id, "notice_id": notice_id, "ts": time.time()}
        self.acknowledgements.append(ack)
        return ack

    def mcp_get_project_status(self, *, agent_id: str) -> dict:
        self._assert_agent_can_work(agent_id)
        return {
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "active_agents": len(self.agents),
            "tasks": {t.task_id: t.status for t in self.tasks.values()},
            "proposals": len(self.proposals),
            "reviews": len(self.reviews),
        }

    def mcp_leave_collective(self, *, agent_id: str) -> dict:
        if agent_id not in self.agents:
            raise KeyError(agent_id)
        self.agents[agent_id].connection_state = "OFFLINE"
        self.agents[agent_id].execution_state = "FINISHED"
        return {"agent_id": agent_id, "connection_state": "OFFLINE"}

    def mcp_get_task_context(self, *, agent_id: str, task_id: str) -> dict:
        self._assert_agent_can_work(agent_id)
        return {"task_id": task_id, "context_packet": self.task_contexts.get(task_id, {})}

    def mcp_list_evidence_refs(self, *, agent_id: str) -> dict:
        self._assert_agent_can_work(agent_id)
        return {"refs": sorted(self.evidence_store)}

    def mcp_retrieve_evidence(self, *, agent_id: str, ref: str) -> dict:
        self._assert_agent_can_work(agent_id)
        if ref not in self.evidence_store:
            return {"status": "not_found", "ref": ref}
        raw = self.evidence_store[ref]
        return {
            "status": "ok",
            "ref": ref,
            "content": raw.decode("utf-8", errors="replace"),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    # ------------------------------------------------------------------ CR-70, CR-61/71, CR-72, CR-73, CR-65
    @staticmethod
    def plan_partition(
        files: dict[str, float],
        edges: list[tuple[str, str, float]],
        *,
        seats_for_builders: int = 2,
    ) -> ref_partitioner.Plan:
        """Cohesion-aware graph partitioning (`CR-70`)."""
        return ref_partitioner.plan(files, edges, seats_for_builders=seats_for_builders)

    @staticmethod
    def evaluate_wave_composition(
        baseline: dict[str, bool],
        per_patch: dict[str, dict[str, bool]],
        combined: dict[str, bool],
        *,
        run_subset: Callable[[tuple[str, ...]], dict[str, bool]] | None = None,
        source_changes: dict[str, dict[str, tuple[str, str]]] | None = None,
        symbol_references: dict[str, set[str]] | None = None,
    ) -> dict:
        """Evaluate `GC_COMPOSITION` wave interference (`CR-61`) and AST symbol-change notices (`CR-71`)."""
        comp = ref_composition_gate.gate(baseline, per_patch, combined, run_subset=run_subset)
        notices = (
            ref_composition_gate.notices_from_sources(source_changes, symbol_references)
            if source_changes is not None and symbol_references is not None
            else {}
        )
        return {
            "decision": comp.decision,
            "interfering_tests": comp.interfering_tests,
            "culprit_pairs": comp.culprit_pairs,
            "reason": comp.reason,
            "ast_notices": notices,
        }

    @staticmethod
    def select_candidate(
        candidates: list[ref_selection.Candidate],
        *,
        risk_level: str = "MEDIUM",
        judge: Callable[[ref_selection.Candidate, ref_selection.Candidate, int], str] | None = None,
    ) -> dict:
        """Execution-evidence-first candidate selection + adaptive-k sampling decision (`CR-72`)."""
        winner, reason = ref_selection.select(candidates, judge=judge)
        sample_more, sample_reason = ref_selection.should_sample_more(candidates, risk_level)
        return {
            "winner": winner,
            "selection_reason": reason,
            "should_sample_more": sample_more,
            "sample_reason": sample_reason,
        }

    @staticmethod
    def run_speculative_tools(
        calls: list[ref_speculative.Call],
        initial_state: dict,
        execute_fn: Callable[[ref_speculative.Call, dict], tuple[object, dict]],
    ) -> dict:
        """Execute read-only speculative tool calls with Tomasulo in-order commit (`CR-73`)."""
        out = ref_speculative.run(calls, initial_state, execute_fn)
        seq = ref_speculative.sequential(calls, initial_state, execute_fn)
        if out["results"] != seq:
            raise CollectiveRuntimeError("speculative execution diverged from sequential baseline")
        return out

    @staticmethod
    def calibrate_and_route_cascade(
        scores: list[float],
        correct: list[int],
        *,
        cost_cheap: float,
        cost_strong: float,
        query_score: float,
        role: str,
        risk_level: str,
    ) -> dict:
        """Fit isotonic PAV cascade threshold and route `(query_score, role, risk_level)` (`CR-73`)."""
        plan = ref_cascade.choose_threshold(scores, correct, cost_cheap, cost_strong)
        tier = ref_cascade.route(query_score, plan, role, risk_level)
        return {"plan": plan, "routed_tier": tier}

    @staticmethod
    def evaluate_ppi_acceptance(
        d_labeled: list[float],
        f_labeled: list[float],
        f_unlabeled: list[float],
        *,
        delta: float,
        metric: str,
        tier: str = "A_canary",
    ) -> dict:
        """Evaluate Prediction-Powered Inference non-inferiority for human acceptance (`CR-65`)."""
        return ref_ppi.noninferiority(d_labeled, f_labeled, f_unlabeled, delta, metric, tier)

    def admit_memory_lesson(self, lesson: ref_memory_policy.Lesson) -> tuple[bool, str]:
        return ref_memory_policy.admit(self.memory_store, lesson)

    def recall_memory_lessons(
        self,
        view: ref_memory_policy.TaskMemoryView,
        phase: str,
        query_tags: set[str],
    ) -> list[ref_memory_policy.Lesson]:
        return ref_memory_policy.recall(self.memory_store, view, phase, query_tags)

    def shred_memory_run(self, run_id: str) -> int:
        return ref_memory_policy.shred_run(self.memory_store, run_id)
