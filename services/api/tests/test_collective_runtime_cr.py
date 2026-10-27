"""Acceptance tests for 5-Seat Collective Runtime, 12-Tool MCP Surface, Compaction Boundary Eval (CR-75), and M6 Harness Optimizer (CR-76)."""
from __future__ import annotations

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evoforge.collective_runtime import (  # noqa: E402
    CANONICAL_MCP_TOOLS,
    CANONICAL_SEAT_LABELS,
    AdaptiveCollectiveCoordinator,
    AgentAccessDeniedError,
    ClaimLostError,
    CompactionBoundaryRuntime,
    CompactionPolicyError,
    ContinuationTurnTrace,
    HarnessOptimizerRuntime,
    StaleWriteError,
    ref_harness_optimizer,
    ref_memory_policy,
    ref_selection,
    ref_speculative,
)


def test_compaction_boundary_folding_and_continuation_eval_cr75() -> None:
    """CR-75: Reversible epoch folding at explicit boundaries + paired 3-turn continuation evaluation."""
    rt = CompactionBoundaryRuntime()

    items = [
        {
            "item_id": "it_plat",
            "layer": "L0_PLATFORM",
            "epoch": 0,
            "requires_original": True,
            "content": "Platform invariant rules",
        },
        {
            "item_id": "it_old_log",
            "layer": "L3_TASK_DELTA",
            "epoch": 0,
            "requires_original": False,
            "ref": "ev_0123456789abcdef0123456789abcdef",
            "content": " pytest run epoch 0 output\n12 passed in 0.41s\n",
        },
        {
            "item_id": "it_old_req",
            "layer": "L3_TASK_DELTA",
            "epoch": 0,
            "requires_original": True,
            "ref": "ev_fedcba9876543210fedcba9876543210",
            "content": "diff --git a/app.py b/app.py\n",
        },
        {
            "item_id": "it_cur_log",
            "layer": "L3_TASK_DELTA",
            "epoch": 1,
            "requires_original": False,
            "ref": "ev_11112222333344445555666677778888",
            "content": "current epoch active trace",
        },
    ]

    # Mid-turn (non-boundary) folding is strictly forbidden
    with pytest.raises(CompactionPolicyError, match="explicit epoch boundaries"):
        rt.fold_epoch_items(items, current_epoch=1, at_epoch_boundary=False)

    folded = rt.fold_epoch_items(items, current_epoch=1, at_epoch_boundary=True)
    by_id = {f.item_id: f for f in folded}

    # L0_PLATFORM, requires_original=True, and current_epoch items stay RAW
    assert by_id["it_plat"].fidelity == "RAW"
    assert by_id["it_old_req"].fidelity == "RAW"
    assert by_id["it_cur_log"].fidelity == "RAW"

    # Prior-epoch L3_TASK_DELTA without requires_original becomes a lossless REF_ONLY stub
    stub = by_id["it_old_log"]
    assert stub.fidelity == "REF_ONLY"
    assert stub.ref == "ev_0123456789abcdef0123456789abcdef"
    assert stub.sha256 is not None and len(stub.sha256) == 64
    assert stub.byte_length == len(items[1]["content"].encode("utf-8"))

    # Recording < 30 sessions is flagged UNDERPOWERED
    for s in range(10):
        rt.record_paired_continuation(
            session_id=f"s{s:03d}",
            boundary_id="b0",
            baseline_seed_runs=[[ContinuationTurnTrace(1, True, 0, 0)] for _ in range(3)],
            candidate_seed_runs=[[ContinuationTurnTrace(1, True, 0, 0)] for _ in range(3)],
        )
    under = rt.evaluate("A_canary")
    assert under["passed"] is False
    assert any("UNDERPOWERED" in r for r in under["reasons"])

    # Populate up to 120 equivalent sessions -> PASS on A_canary
    for s in range(10, 120):
        rt.record_paired_continuation(
            session_id=f"s{s:03d}",
            boundary_id="b0",
            baseline_seed_runs=[
                [ContinuationTurnTrace(1, False, 1, 0), ContinuationTurnTrace(2, True, 0, 1)]
                for _ in range(3)
            ],
            candidate_seed_runs=[
                [ContinuationTurnTrace(1, False, 1, 0), ContinuationTurnTrace(2, True, 0, 1)]
                for _ in range(3)
            ],
        )
    passed = rt.evaluate("A_canary")
    assert passed["passed"] is True, passed["reasons"]

    # Repeated exploration spike fails even when success rate is identical
    rt_bad = CompactionBoundaryRuntime()
    for s in range(120):
        rt_bad.record_paired_continuation(
            session_id=f"s{s:03d}",
            boundary_id="b0",
            baseline_seed_runs=[[ContinuationTurnTrace(1, True, 1, 0)] for _ in range(3)],
            candidate_seed_runs=[[ContinuationTurnTrace(1, True, 3, 0)] for _ in range(3)],
        )
    failed_rep = rt_bad.evaluate("A_canary")
    assert failed_rep["passed"] is False
    assert any("repeated exploration" in r for r in failed_rep["reasons"])


def test_harness_optimizer_runtime_loop_cr76() -> None:
    """CR-76: M6 Harness Optimizer state machine, schema validation, Trust Kernel protection, and budget annealing."""
    initial_files = {
        "prompts/builder.md": "## Rules\n- be careful\n",
        "tools/search.py": "def search(q):\n    return []\n",
        "policy/engine.py": "def allow():\n    return False\n",
    }

    # Baseline must be GEPA
    with pytest.raises(ref_harness_optimizer.OptimizerError, match="baseline must be GEPA"):
        HarnessOptimizerRuntime("run_bad", initial_files, baseline="random-search")

    opt = HarnessOptimizerRuntime("run_m6", initial_files, total_generations=11)

    def make_patch(ops: list[dict], *, patch_id: str = "hp_00000001", gen: int = 0, parents: list[str] | None = None, extra: dict | None = None) -> dict:
        doc = {
            "schema_version": "harness-patch/v1",
            "patch_id": patch_id,
            "run_id": "run_m6",
            "generation": gen,
            "parent_versions": parents or ["hv_00000001"],
            "module": "C",
            "category": "prompt",
            "phase": "steering",
            "ops": ops,
            "rationale": "preserve recent context across epoch boundaries",
        }
        if extra:
            doc.update(extra)
        return doc

    # 1) D_test is unrepresentable in harness-patch/v1 schema
    bad_test_tag = make_patch(
        [{"file": "prompts/builder.md", "op": "insert_after", "anchor": "## Rules\n", "text": "- check\n"}],
        extra={"evaluated_on": ["test"]},
    )
    with pytest.raises(ref_harness_optimizer.OptimizerError, match="invalid harness-patch/v1 schema"):
        opt.propose_and_apply(
            candidate_version_id="hv_badtest1",
            patch=bad_test_tag,
            parent_minibatch=0.5,
            child_minibatch=0.7,
        )

    # 2) Touching Trust Kernel (`policy/engine.py`) is rejected
    tk_patch = make_patch(
        [{"file": "policy/engine.py", "op": "replace", "anchor": "return False", "text": "return True", "lines": 1}],
        patch_id="hp_tk000001",
    )
    with pytest.raises(ref_harness_optimizer.OptimizerError, match="Trust Kernel"):
        opt.propose_and_apply(
            candidate_version_id="hv_tk000001",
            patch=tk_patch,
            parent_minibatch=0.5,
            child_minibatch=0.8,
        )

    # 3) Late-generation edit budget annealing (gen 10 budget = 20 lines) rejects 30-line patch
    big_patch = make_patch(
        [{"file": "prompts/builder.md", "op": "insert_after", "anchor": "## Rules\n", "text": "- rule\n" * 30}],
        patch_id="hp_big00001",
        gen=10,
    )
    with pytest.raises(ref_harness_optimizer.OptimizerError, match="edit budget exceeded"):
        opt.propose_and_apply(
            candidate_version_id="hv_big00001",
            patch=big_patch,
            parent_minibatch=0.5,
            child_minibatch=0.8,
        )

    # 4) Non-improving minibatch patch is not promoted to candidate
    valid_p1 = make_patch(
        [{"file": "prompts/builder.md", "op": "insert_after", "anchor": "## Rules\n", "text": "- verify first\n"}],
        patch_id="hp_valid001",
        gen=1,
    )
    accepted_no, snap_no = opt.propose_and_apply(
        candidate_version_id="hv_00000002",
        patch=valid_p1,
        parent_minibatch=0.55,
        child_minibatch=0.55,
    )
    assert accepted_no is False and snap_no is None

    # 5) Improving minibatch patch is applied and registered in EvoDAG
    accepted_yes, snap_yes = opt.propose_and_apply(
        candidate_version_id="hv_00000002",
        patch=valid_p1,
        parent_minibatch=0.55,
        child_minibatch=0.68,
    )
    assert accepted_yes is True and snap_yes is not None
    assert "- verify first\n" in snap_yes.files["prompts/builder.md"]

    # Second candidate hv_00000003 composing hv_00000001 and hv_00000002
    valid_p2 = make_patch(
        [{"file": "prompts/builder.md", "op": "insert_before", "anchor": "- be careful\n", "text": "- inspect AST\n"}],
        patch_id="hp_valid002",
        gen=2,
        parents=["hv_00000002", "hv_00000001"],
    )
    ok2, _ = opt.propose_and_apply(
        candidate_version_id="hv_00000003",
        patch=valid_p2,
        parent_minibatch=0.68,
        child_minibatch=0.72,
    )
    assert ok2 is True

    opt.evaluate_dev("hv_00000002", 0.74)
    opt.evaluate_dev("hv_00000003", 0.69)
    assert opt.select_best_dev() == "hv_00000002"

    rng = random.Random(42)
    winning_pairs = [(f"t{i:03d}", b := int(rng.random() < 0.5), 1 if (b == 1 or rng.random() < 0.35) else 0) for i in range(200)]

    # Cannot freeze non-top dev candidate
    with pytest.raises(ref_harness_optimizer.OptimizerError, match="dev-selected"):
        opt.freeze_winner("hv_00000003", winning_pairs)

    # Freeze winner -> state becomes FROZEN
    opt.freeze_winner("hv_00000002", winning_pairs)
    assert opt.state == "FROZEN"

    # Cannot propose new patches after freeze (no test-to-harness feedback loop)
    with pytest.raises(ref_harness_optimizer.OptimizerError, match="no new patches after freeze"):
        opt.propose_and_apply(
            candidate_version_id="hv_00000004",
            patch=valid_p1,
            parent_minibatch=0.5,
            child_minibatch=0.9,
        )

    # Evaluate D_test once -> state becomes CLOSED; second D_test call is rejected
    res = opt.evaluate_test_once("hv_00000002", 0.71)
    assert res["state"] == "CLOSED"
    assert res["d_test_score"] == 0.71
    with pytest.raises(ref_harness_optimizer.OptimizerError, match="D_test only for the frozen candidate, once"):
        opt.evaluate_test_once("hv_00000002", 0.72)


def test_5_seat_mcp_onboarding_and_lease_fencing_cr59_cr60() -> None:
    """CR-59 & CR-60: 5-seat registration, 12 canonical MCP tools, credential checks, and lease_epoch fencing."""
    coord = AdaptiveCollectiveCoordinator("tenant_1", "proj_1")
    assert len(CANONICAL_SEAT_LABELS) == 5
    assert len(CANONICAL_MCP_TOOLS) == 12

    seats_and_roles = [
        ("ag_nav", "Navigator", "planner"),
        ("ag_ba", "Builder Alpha", "builder"),
        ("ag_bb", "Builder Beta", "builder"),
        ("ag_crit", "Critic", "critic"),
        ("ag_int", "Integrator", "integrator"),
    ]
    for aid, seat, role in seats_and_roles:
        coord.invoke_mcp_tool(
            "join_collective",
            agent_id=aid,
            seat_label=seat,
            function_role=role,
        )

    # CR-59: Unapproved or expired-credential agent cannot claim tasks or read context
    coord.invoke_mcp_tool(
        "join_collective",
        agent_id="ag_expired",
        seat_label="Builder Beta",
        function_role="builder",
        credential_state="EXPIRED",
    )
    coord.register_task("task_1", "run_1", "HIGH", context_packet={"packet_id": "pkt_1"})
    coord.evidence_store["ev_0001"] = b"raw test failure log"

    with pytest.raises(AgentAccessDeniedError):
        coord.invoke_mcp_tool("claim_task", agent_id="ag_expired", task_id="task_1")

    # CR-60: Builder Alpha claims task_1 at t=1000 -> epoch 1; Builder Beta concurrent claim fails with CLAIM_LOST
    c1 = coord.invoke_mcp_tool("claim_task", agent_id="ag_ba", task_id="task_1", ttl_seconds=60.0, now=1000.0)
    assert c1["lease_epoch"] == 1
    with pytest.raises(ClaimLostError):
        coord.invoke_mcp_tool("claim_task", agent_id="ag_bb", task_id="task_1", ttl_seconds=60.0, now=1020.0)

    # Lease expires at t=1061 -> Builder Beta reclaims and bumps lease_epoch to 2
    c2 = coord.invoke_mcp_tool("claim_task", agent_id="ag_bb", task_id="task_1", ttl_seconds=60.0, now=1065.0)
    assert c2["lease_epoch"] == 2

    # Late write by Builder Alpha presenting stale epoch 1 is rejected with STALE_WRITE
    with pytest.raises(StaleWriteError, match="STALE_WRITE"):
        coord.invoke_mcp_tool(
            "submit_proposal",
            agent_id="ag_ba",
            task_id="task_1",
            lease_epoch=1,
            candidate_id="cand_stale",
            diff="diff --git a/x.py b/x.py\n",
            now=1070.0,
        )

    # Current holder Builder Beta with epoch 2 succeeds
    prop = coord.invoke_mcp_tool(
        "submit_proposal",
        agent_id="ag_bb",
        task_id="task_1",
        lease_epoch=2,
        candidate_id="cand_ok",
        diff="diff --git a/x.py b/x.py\n",
        now=1070.0,
    )
    assert prop["candidate_id"] == "cand_ok"

    # Author cannot review own candidate; Critic reviews with independent verdict
    with pytest.raises( Exception, match="author cannot review own candidate"):
        coord.invoke_mcp_tool("submit_review", agent_id="ag_bb", candidate_id="cand_ok", verdict="approve")
    rev = coord.invoke_mcp_tool("submit_review", agent_id="ag_crit", candidate_id="cand_ok", verdict="approve")
    assert rev["verdict"] == "approve"

    # Exercise remaining MCP tools (get_my_tasks, post_message, acknowledge, get_project_status,
    # get_task_context, list_evidence_refs, retrieve_evidence, leave_collective)
    assert len(coord.invoke_mcp_tool("get_my_tasks", agent_id="ag_bb")["tasks"]) == 1
    coord.invoke_mcp_tool("post_message", agent_id="ag_nav", channel="wave", body="interface frozen")
    coord.invoke_mcp_tool("acknowledge", agent_id="ag_bb", notice_id="nt_1")
    status = coord.invoke_mcp_tool("get_project_status", agent_id="ag_int")
    assert status["proposals"] == 1 and status["reviews"] == 1
    assert coord.invoke_mcp_tool("get_task_context", agent_id="ag_bb", task_id="task_1")["context_packet"]["packet_id"] == "pkt_1"
    assert coord.invoke_mcp_tool("list_evidence_refs", agent_id="ag_crit")["refs"] == ["ev_0001"]
    ev = coord.invoke_mcp_tool("retrieve_evidence", agent_id="ag_crit", ref="ev_0001")
    assert ev["status"] == "ok" and ev["content"] == "raw test failure log"
    left = coord.invoke_mcp_tool("leave_collective", agent_id="ag_nav")
    assert left["connection_state"] == "OFFLINE"


def test_adaptive_collective_partition_composition_selection_speculation_cascade_ppi_memory_cr61_65_70_71_72_73() -> None:
    """CR-61, CR-65, CR-70, CR-71, CR-72, CR-73 end-to-end verification through AdaptiveCollectiveCoordinator."""
    coord = AdaptiveCollectiveCoordinator("tenant_1", "proj_1")

    # 1) CR-70: Cohesion-aware partitioning chooses DAG_PARALLEL for two cohesive modules, SINGLE for coupled clique
    cohesive_files = {"hub.py": 1.0, "a1.py": 5.0, "a2.py": 5.0, "b1.py": 5.0, "b2.py": 5.0}
    cohesive_edges = [
        ("hub.py", "a1.py", 1.0),
        ("hub.py", "a2.py", 1.0),
        ("hub.py", "b1.py", 1.0),
        ("hub.py", "b2.py", 1.0),
        ("a1.py", "a2.py", 10.0),
        ("b1.py", "b2.py", 10.0),
    ]
    plan_par = coord.plan_partition(cohesive_files, cohesive_edges, seats_for_builders=2)
    assert plan_par.topology == "DAG_PARALLEL"
    assert plan_par.hubs == ["hub.py"]

    coupled_files = {"x.py": 2.0, "y.py": 2.0, "z.py": 2.0}
    coupled_edges = [("x.py", "y.py", 5.0), ("y.py", "z.py", 5.0), ("x.py", "z.py", 5.0)]
    plan_single = coord.plan_partition(coupled_files, coupled_edges, seats_for_builders=2)
    assert plan_single.topology == "SINGLE"

    # 2) CR-61 & CR-71: Wave composition gate + culprit attribution + AST symbol-change notices
    base_res = {"t1": True, "t2": True}
    per_patch = {"p1": {"t1": True, "t2": True}, "p2": {"t1": True, "t2": True}, "p3": {"t1": True, "t2": True}}
    combined = {"t1": True, "t2": False}
    comp = coord.evaluate_wave_composition(
        base_res,
        per_patch,
        combined,
        run_subset=lambda pair: {"t1": True, "t2": pair != ("p1", "p2")},
        source_changes={
            "p1": {
                "pkg/api.py": (
                    "def compute(x):\n    return x\n\ndef helper(y):\n    return y\n",
                    "def compute(x, scale=1):\n    return x * scale\n\ndef helper(y):\n    return y + 1\n",
                )
            }
        },
        symbol_references={"p2": {"compute", "helper"}, "p1": {"compute"}},
    )
    assert comp["decision"] == "FAIL"
    assert comp["culprit_pairs"] == [("p1", "p2")]
    # AST notice sent to p2 ONLY for `compute` (signature changed), NOT `helper` (body-only change)
    assert [(n["symbol"], n["kind"]) for n in comp["ast_notices"]["p2"]] == [("compute", "signature_changed")]

    # 3) CR-72: Execution-evidence-first candidate selection + adaptive-k
    c_hack = ref_selection.Candidate("c_hack", True, True, 10, 10, 10, 10, 20, "sig1")
    c_good = ref_selection.Candidate("c_good", True, False, 10, 10, 10, 10, 80, "sig1")
    c_weak = ref_selection.Candidate("c_weak", True, False, 6, 10, 6, 10, 30, "sig2")
    sel = coord.select_candidate([c_hack, c_good, c_weak], risk_level="LOW")
    assert sel["winner"].cid == "c_good"
    assert sel["should_sample_more"] is False  # full pass at LOW risk stops early

    # 4) CR-73: Speculative read-only execution (0 false accepts, side-effect calls never speculated)
    calls = [
        ref_speculative.Call("c1", "fs.read", reads=frozenset({"a.py"})),
        ref_speculative.Call("c2", "fs.write", reads=frozenset({"a.py"}), writes=frozenset({"a.py"})),
        ref_speculative.Call("c3", "fs.read", reads=frozenset({"a.py"})),
        ref_speculative.Call("c4", "search.code", reads=frozenset({"b.py"})),
    ]
    spec_out = coord.run_speculative_tools(
        calls,
        {"a.py": "v1", "b.py": "stable"},
        lambda call, st: (
            (st["a.py"], {})
            if call.kind == "fs.read"
            else (st["b.py"], {})
            if call.kind == "search.code"
            else ("patched", {"a.py": "v2"})
        ),
    )
    assert spec_out["results"] == ["v1", "patched", "v2", "stable"]
    assert spec_out["accepted"] >= 1 and spec_out["reexecuted"] >= 1

    # 5) CR-73: Isotonic PAV cascade routing (disabled for critic/HIGH risk)
    scores = [i / 320.0 for i in range(320)]
    labels = [0 if s < 0.5 else 1 for s in scores]
    casc_builder = coord.calibrate_and_route_cascade(
        scores, labels, cost_cheap=1.0, cost_strong=10.0, query_score=0.95, role="builder", risk_level="LOW"
    )
    assert casc_builder["plan"]["enabled"] is True
    assert casc_builder["routed_tier"] == "cheap"
    casc_critic = coord.calibrate_and_route_cascade(
        scores, labels, cost_cheap=1.0, cost_strong=10.0, query_score=0.99, role="critic", risk_level="LOW"
    )
    assert casc_critic["routed_tier"] == "strong"

    # 6) CR-65: PPI non-inferiority allowed for human_acceptance, blocked for safety
    ppi_blocked = coord.evaluate_ppi_acceptance(
        [0.0] * 100, [0.0] * 100, [0.0] * 500, delta=0.02, metric="safety"
    )
    assert ppi_blocked["decision"] == "NOT_ALLOWED"
    ppi_ok = coord.evaluate_ppi_acceptance(
        [0.01 if i % 2 == 0 else 0.02 for i in range(90)],
        [0.01 if i % 2 == 0 else 0.02 for i in range(90)],
        [0.015 if i % 2 == 0 else 0.02 for i in range(300)],
        delta=0.02,
        metric="human_acceptance",
        tier="A_canary",
    )
    assert ppi_ok["decision"] == "PASS"

    # 7) CR-73: Phase-gated experience memory (admit only verified_improvement, 1-exposure eviction, shred_run)
    bad_lesson = ref_memory_policy.Lesson("L_bad", "tenant_1", "fix", frozenset({"ast", "types"}), "bad", "run_x", "unverified_run")
    assert coord.admit_memory_lesson(bad_lesson)[0] is False
    good_lesson = ref_memory_policy.Lesson("L_ok", "tenant_1", "fix", frozenset({"ast", "types"}), "check AST defaults", "run_x", "verified_improvement")
    assert coord.admit_memory_lesson(good_lesson)[0] is True
    view = ref_memory_policy.TaskMemoryView("tenant_1")
    assert len(coord.recall_memory_lessons(view, "fix", {"ast", "types"})) == 1
    assert len(coord.recall_memory_lessons(view, "fix", {"ast", "types"})) == 0  # evicted after 1 exposure in task
    assert coord.shred_memory_run("run_x") == 1
