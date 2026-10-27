"""Acceptance tests for Large Diff Splitting (CR-32), Review Coverage Ledger
(CR-08, CR-10, CR-14, CR-32), and Seeded-Defect Canary / Reviewer Qualification
Pool (CR-34, CR-58, CR-66, CR-68).
"""
from __future__ import annotations

import hashlib
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evoforge.review_qualification import (
    ReviewCoverageLedger,
    ReviewerQualificationPool,
    plan_diff_review,
)


def _make_multi_file_diff(num_files: int, body_Repeat: int) -> str:
    blocks: list[str] = []
    for f_idx in range(num_files):
        path = f"services/mod_{f_idx:02d}.py"
        hunk_lines = "\n".join(f"+    val_{k} = {k} * 2" for k in range(body_Repeat))
        blocks.append(
            f"--- a/{path}\n+++ b/{path}\n@@ -1,2 +1,{body_Repeat + 2} @@\n def run():\n{hunk_lines}\n     return True\n"
        )
    return "".join(blocks)


def _sample_critic_packet(agent_id: str, repo_sha: str, diff_bytes_len: int) -> dict:
    h = hashlib.sha256(b"contract").hexdigest()
    return {
        "schema_version": "context-packet/v2",
        "packet_id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "project_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "task_attempt_id": str(uuid.uuid4()),
        "idempotency_key": "task-02:attempt-01:seat-4:ctx",
        "issued_at": "2026-10-25T09:00:00Z",
        "expires_at": "2026-10-25T10:00:00Z",
        "supersedes_packet_id": None,
        "profile": "SAFE",
        "experiment_arm": None,
        "recipient": {
            "seat_id": 4,
            "seat_label": "Critic",
            "function_role": "critic",
            "agent_id": agent_id,
            "candidate_id": str(uuid.uuid4()),
            "is_author_of_candidate": False,
            "channel": "mcp",
        },
        "fencing": {
            "repo_sha": repo_sha,
            "contract_version": 3,
            "policy_version": "policy-7",
            "policy_hash": h,
            "tool_schema_hash": h,
            "evidence_manifest_hash": h,
            "lease_epoch": 12,
        },
        "items": [
            {
                "item_id": "it_goal",
                "source_kind": "contract.goal",
                "ref": "evr_0q3m8k2v7c4t1n6h9w5r2x8z3b",
                "sha256": h,
                "size_bytes": 64,
                "trust": "trusted_contract",
                "classification": "internal",
                "requires_original": True,
                "fidelity": "RAW",
                "raw_reason": "POLICY_REQUIRED",
                "segment_index": 1,
                "view_sha256": h,
                "view_tokens_est": 16,
            },
            {
                "item_id": "it_diff",
                "source_kind": "git.diff",
                "ref": "evr_7y6x5w4v3t2s1r0q9p8n7m6k5j",
                "sha256": h,
                "size_bytes": diff_bytes_len,
                "trust": "verified_tool_output",
                "classification": "restricted",
                "requires_original": True,
                "fidelity": "REF_ONLY",
                "segment_index": 3,
                "view_sha256": hashlib.sha256(b"").hexdigest(),
                "view_tokens_est": 0,
            },
        ],
        "critical_assertions": [],
        "layout": {
            "prefix_layout": "STABLE_PREFIX",
            "serialization": "evoforge-canonical/v1",
            "cache_namespace_id": "cns_01jb7m3k9q2w4e6r8t0y1v3j5p",
            "segments": [],
        },
        "cache_plan": {
            "provider": "anthropic",
            "model": "claude-opus-5-5",
            "cache_mode": "PROVIDER_EXPLICIT",
            "registry_entry_id": "anthropic.claude-current",
            "registry_verified_at": "2026-10-25",
        },
        "recovery": {
            "channels": ["mcp", "rest"],
            "max_bytes_per_call": 262144,
            "max_calls": 40,
            "refs_expire_at": "2026-10-25T10:00:00Z",
        },
    }


def test_large_diff_splitting_and_chunk_review_coverage_cr08_cr10_cr14_cr32():
    """CR-08 (incomplete diff coverage rejected), CR-10 (head SHA move rejected),
    CR-14 (chat channel without recovery rejected), CR-32 (>409,600B diff requires split
    or human reviewer; chunked review aggregates byte coverage to 100%).
    """
    # 1. Diff > max_reviewable_diff_bytes (409,600B) -> REQUIRES_SPLIT_OR_HUMAN
    oversized_diff = _make_multi_file_diff(num_files=6, body_Repeat=4000)
    assert len(oversized_diff.encode("utf-8")) > 409_600
    plan_over = plan_diff_review(oversized_diff, max_safe_context_bytes=32_768)
    assert plan_over.status == "REQUIRES_SPLIT_OR_HUMAN"
    assert plan_over.requires_pr_split is True
    assert plan_over.requires_human_reviewer is True
    assert len(plan_over.proposed_pr_splits) >= 2

    # 2. Medium diff (exceeds max_safe_context_bytes=1024, within 409,600B) -> CHUNKED_REVIEW
    medium_diff = _make_multi_file_diff(num_files=4, body_Repeat=40)
    med_bytes = len(medium_diff.encode("utf-8"))
    assert 1024 < med_bytes < 409_600
    plan_chunk = plan_diff_review(medium_diff, max_safe_context_bytes=1024)
    assert plan_chunk.status == "CHUNKED_REVIEW"
    assert len(plan_chunk.chunks) >= 2
    assert plan_chunk.cross_chunk_pass is not None
    assert plan_chunk.cross_chunk_pass.call_purpose == "review_cross_chunk"

    # Verify chunk coverage union in ReviewCoverageLedger (CR-08, CR-32)
    critic_id = str(uuid.uuid4())
    other_agent = str(uuid.uuid4())
    head_sha = "3f9a3f9a3f9a3f9a3f9a3f9a3f9a3f9a3f9a3f9a"
    pkt = _sample_critic_packet(critic_id, head_sha, med_bytes)

    ledger = ReviewCoverageLedger()
    ledger.register_packet(pkt)  # covers inline RAW contract.goal (64 bytes), not REF_ONLY git.diff

    # CR-08: Before reading all diff chunks, approval is rejected
    ok_before, reasons_before = ledger.assert_review_gate(
        pkt, reviewer_agent_id=critic_id, candidate_head_sha=head_sha
    )
    assert ok_before is False
    assert any("CR-08" in r for r in reasons_before)

    # Bytes read by a DIFFERENT agent do not count toward critic_id's coverage
    ledger.record_delivery(
        agent_id=other_agent,
        packet_id=pkt["packet_id"],
        ref="evr_7y6x5w4v3t2s1r0q9p8n7m6k5j",
        byte_start=0,
        byte_end=med_bytes,
        total_bytes=med_bytes,
    )
    assert ledger.item_coverage(critic_id, pkt["packet_id"], "evr_7y6x5w4v3t2s1r0q9p8n7m6k5j", med_bytes)["covered_bytes"] == 0

    # Deliver all chunks except the last -> still incomplete
    for ch in plan_chunk.chunks[:-1]:
        ledger.record_delivery(
            agent_id=critic_id,
            packet_id=pkt["packet_id"],
            ref="evr_7y6x5w4v3t2s1r0q9p8n7m6k5j",
            byte_start=ch.byte_start,
            byte_end=ch.byte_end,
            total_bytes=med_bytes,
        )
    ok_partial, _ = ledger.assert_review_gate(pkt, reviewer_agent_id=critic_id, candidate_head_sha=head_sha)
    assert ok_partial is False

    # Deliver final chunk -> 100% byte coverage achieved!
    last_ch = plan_chunk.chunks[-1]
    ledger.record_delivery(
        agent_id=critic_id,
        packet_id=pkt["packet_id"],
        ref="evr_7y6x5w4v3t2s1r0q9p8n7m6k5j",
        byte_start=last_ch.byte_start,
        byte_end=last_ch.byte_end,
        total_bytes=med_bytes,
    )
    ok_full, reasons_full = ledger.assert_review_gate(pkt, reviewer_agent_id=critic_id, candidate_head_sha=head_sha)
    assert ok_full is True and reasons_full == []

    # CR-10: If candidate head SHA moves after review, approval is rejected
    moved_sha = "9b9b9b9b9b9b9b9b9b9b9b9b9b9b9b9b9b9b9b9b"
    ok_moved, reasons_moved = ledger.assert_review_gate(pkt, reviewer_agent_id=critic_id, candidate_head_sha=moved_sha)
    assert ok_moved is False
    assert any("CR-10" in r for r in reasons_moved)

    # CR-14: Chat channel without recovery tools is rejected
    pkt_chat = dict(pkt, recipient=dict(pkt["recipient"], channel="chat"), recovery={"channels": []})
    ok_chat, reasons_chat = ledger.assert_review_gate(pkt_chat, reviewer_agent_id=critic_id, candidate_head_sha=head_sha)
    assert ok_chat is False
    assert any("CR-14" in r for r in reasons_chat)


def test_seeded_defect_canary_and_reviewer_qualification_pool_cr34_cr58_cr66_cr68():
    """CR-34 (seeded-defect canary excludes underperforming reviewer from pool),
    CR-58 (97/100 qualifies, 95/100 fails, false-block > 10% fails, missing precision fails),
    CR-66 (HIGH risk requires qualified + context-independent + spec-first + counterexample + human),
    CR-68 (100% recall with noisy findings fails Wilson precision LB < 0.40).
    """
    pool = ReviewerQualificationPool()

    # CR-58: 97/100 critical recall, 3/100 false block, 55/100 finding precision -> QUALIFIED
    rec_pass = pool.evaluate_exam(
        reviewer_id="rev_muse_safe_v1",
        model="muse-spark-1.3",
        model_revision="2026-10-25",
        profile="SAFE",
        harness_version="v4.2.0",
        risk_levels={"LOW", "MEDIUM", "HIGH", "CRITICAL"},
        critical_caught=97,
        critical_seeded=100,
        false_blocks=3,
        clean_candidates=100,
        findings_valid=55,
        findings_total=100,
    )
    assert rec_pass.qualified is True
    assert "rev_muse_safe_v1" in pool.active_approver_pool(risk="HIGH")

    # CR-58: 95/100 critical recall -> Wilson 95% LB is ~0.888 < 0.90 -> FAILS
    rec_low_recall = pool.evaluate_exam(
        reviewer_id="rev_95_recall",
        model="muse-spark-1.3",
        model_revision="2026-10-25",
        profile="SAFE",
        harness_version="v4.2.0",
        risk_levels={"HIGH"},
        critical_caught=95,
        critical_seeded=100,
        false_blocks=2,
        clean_candidates=100,
        findings_valid=60,
        findings_total=100,
    )
    assert rec_low_recall.qualified is False
    assert "critical recall Wilson LB" in rec_low_recall.reason

    # CR-68: 100/100 recall, but noisy findings (35/100 valid -> Wilson LB ~0.264 < 0.40) -> FAILS
    rec_noisy = pool.evaluate_exam(
        reviewer_id="rev_noisy_100_recall",
        model="muse-spark-1.3",
        model_revision="2026-10-25",
        profile="SAFE",
        harness_version="v4.2.0",
        risk_levels={"HIGH"},
        critical_caught=100,
        critical_seeded=100,
        false_blocks=2,
        clean_candidates=100,
        findings_valid=35,
        findings_total=100,
    )
    assert rec_noisy.qualified is False
    assert "finding precision Wilson LB" in rec_noisy.reason
    assert "rev_noisy_100_recall" not in pool.active_approver_pool(risk="HIGH")

    # CR-66: HIGH risk merge authorization checks qualification, version match, spec-first,
    # context independence, counterexample feedback, and human approval
    valid_verifier_trace = {
        "inputs": ["goal_contract", "policy", "spec", "diff", "ci_results", "verifier_own_tests"],
        "spec_tests_sealed_at": "2026-10-27T09:00:00Z",
        "diff_first_read_at": "2026-10-27T09:05:00Z",
        "feedback": [
            {
                "kind": "counterexample",
                "failing_input": "x=-1",
                "expected": "ValueError",
                "observed": "0",
                "test_ref": "test_negative_input",
            }
        ],
    }

    ok_high, reasons_high = pool.authorize_high_risk_merge(
        risk="HIGH",
        reviewer_id="rev_muse_safe_v1",
        model_revision="2026-10-25",
        profile="SAFE",
        harness_version="v4.2.0",
        verifier_trace=valid_verifier_trace,
        human_approved=True,
    )
    assert ok_high is True and reasons_high == []

    # Missing human approval on HIGH risk -> rejected (CR-66)
    ok_no_human, reasons_no_human = pool.authorize_high_risk_merge(
        risk="HIGH",
        reviewer_id="rev_muse_safe_v1",
        model_revision="2026-10-25",
        profile="SAFE",
        harness_version="v4.2.0",
        verifier_trace=valid_verifier_trace,
        human_approved=False,
    )
    assert ok_no_human is False
    assert any("human approval" in r for r in reasons_no_human)

    # Harness version or model revision change triggers automatic requalification (CR-66)
    ok_diff_harness, reasons_diff_harness = pool.authorize_high_risk_merge(
        risk="HIGH",
        reviewer_id="rev_muse_safe_v1",
        model_revision="2026-10-25",
        profile="SAFE",
        harness_version="v4.3.0-new",
        verifier_trace=valid_verifier_trace,
        human_approved=True,
    )
    assert ok_diff_harness is False
    assert any("requalification required" in r for r in reasons_diff_harness)

    # CR-34: Seeded-defect canary degradation removes reviewer from active approver pool
    pool.record_canary_probe("rev_muse_safe_v1", canary_caught=85, canary_seeded=100)
    assert "rev_muse_safe_v1" not in pool.active_approver_pool(risk="HIGH")


def test_single_pass_diff_and_high_risk_independence_violations_cr66():
    """Verify SINGLE_PASS diff plan and CR-66 independence rejections (forbidden input,
    wrong phase order, non-counterexample feedback).
    """
    small_diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    plan = plan_diff_review(small_diff, max_safe_context_bytes=4096)
    assert plan.status == "SINGLE_PASS"
    assert len(plan.chunks) == 1
    assert plan.cross_chunk_pass is None

    pool = ReviewerQualificationPool()
    pool.evaluate_exam(
        reviewer_id="rev_ok",
        model="muse-spark-1.3",
        model_revision="2026-10-25",
        profile="SAFE",
        harness_version="v4.2.0",
        risk_levels={"HIGH"},
        critical_caught=98,
        critical_seeded=100,
        false_blocks=1,
        clean_candidates=100,
        findings_valid=70,
        findings_total=100,
    )

    # Leaking builder_rationale & reading diff before sealing spec tests & invalid feedback -> rejected
    bad_trace = {
        "inputs": ["goal_contract", "builder_rationale", "diff"],
        "spec_tests_sealed_at": "2026-10-27T09:10:00Z",
        "diff_first_read_at": "2026-10-27T09:05:00Z",
        "feedback": [{"kind": "freeform_opinion", "note": "looks bad"}],
    }
    ok, reasons = pool.authorize_high_risk_merge(
        risk="HIGH",
        reviewer_id="rev_ok",
        model_revision="2026-10-25",
        profile="SAFE",
        harness_version="v4.2.0",
        verifier_trace=bad_trace,
        human_approved=True,
    )
    assert ok is False
    assert any("context not independent" in r for r in reasons)
    assert any("phase order violated" in r for r in reasons)
    assert any("counterexample" in r for r in reasons)

