"""Acceptance tests for Observability, SLO vs Safety Invariants, Billing Drift/Webhooks, and Lifecycle Governance."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evoforge.observability_and_governance import (
    BillingInvoiceAndWebhookReconciler,
    CANONICAL_CONTEXT_SPANS,
    CanonicalTelemetryTracer,
    GovernanceError,
    IncidentAndLifecycleGovernance,
    SLOVsSafetyMonitor,
    SUPPLY_CHAIN_RUNBOOK_STEPS,
)


TENANT_ID = "11111111-1111-4111-8111-111111111111"
PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_canonical_telemetry_and_slo_vs_safety_panel_separation_r47_2() -> None:
    """R47-2: Canonical context/workflow spans validated; Service SLO panel and Safety Invariant panel separated."""
    tracer = CanonicalTelemetryTracer()
    trace_id = "trace-e2e-001"

    for span_name in sorted(CANONICAL_CONTEXT_SPANS):
        tracer.record_span(
            trace_id=trace_id,
            name=span_name,
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            duration_ms=12.5,
        )
    assert len(tracer.spans_for_trace(trace_id)) == 6

    with pytest.raises(GovernanceError) as exc_span:
        tracer.record_span(
            trace_id=trace_id,
            name="non_canonical.span",
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            duration_ms=1.0,
        )
    assert exc_span.value.code == "UNKNOWN_CANONICAL_SPAN"

    monitor = SLOVsSafetyMonitor()
    dash_clean = monitor.evaluate_dashboard_panels(
        valid_requests=10_000,
        successful_responses=9_995,  # 99.95% >= 99.9%
        command_ack_p95_ms=420.0,
        ui_commit_reflect_p95_ms=1100.0,
        reconnect_converge_p95_ms=3400.0,
        stop_all_apply_p95_ms=1800.0,
    )
    assert dash_clean["panels_separated"] is True
    assert dash_clean["service_slo_panel"]["all_met"] is True
    assert dash_clean["safety_invariant_panel"]["healthy"] is True
    assert dash_clean["safety_invariant_panel"]["total_violations"] == 0

    # A single safety invariant violation must fail the safety panel and open an incident even while SLOs are green
    monitor.record_safety_violation("unauthorized_platform_key_decrypt", details="worker-sa attempted KMS decrypt")
    dash_violated = monitor.evaluate_dashboard_panels(
        valid_requests=10_000,
        successful_responses=9_999,
        command_ack_p95_ms=300.0,
        ui_commit_reflect_p95_ms=900.0,
        reconnect_converge_p95_ms=2000.0,
        stop_all_apply_p95_ms=1000.0,
    )
    assert dash_violated["service_slo_panel"]["all_met"] is True
    assert dash_violated["safety_invariant_panel"]["healthy"] is False
    assert dash_violated["safety_invariant_panel"]["total_violations"] == 1
    assert dash_violated["safety_invariant_panel"]["active_incidents"] == 1


def test_performance_technique_monitor_speculation_killswitch_and_reward_hacking_r47_4() -> None:
    """R47-4: 1 speculation mismatch disables speculation globally; reward-hacking spike quarantines canary; runner >=80% throttles."""
    monitor = SLOVsSafetyMonitor()

    # Healthy run
    healthy = monitor.evaluate_performance_techniques(
        model="muse-spark-1.3",
        harness_version="h_v1.0",
        composition_runs=50,
        composition_interferences=1,
        integrity_evals=100,
        integrity_flags=2,
        visible_pass_rate=0.88,
        heldout_pass_rate=0.84,
        speculation_trials=300,
        speculation_accepted=240,
        speculation_mismatches=0,
        samples_per_task_k=1.4,
        cascade_trials=350,
        cascade_escalations=70,
        verification_runner_utilization=0.65,
        runner_utilization_increasing=False,
    )
    assert healthy["speculation_globally_enabled"] is True
    assert healthy["reward_hacking_alert"] is False
    assert healthy["canary_quarantined"] is False
    assert healthy["runner_capacity_action"] == "NORMAL"
    assert healthy["technique_panels"]["speculation"]["n"] == 300

    # 1 speculation mismatch + high visible/heldout gap + runner utilization >= 80% increasing
    tripped = monitor.evaluate_performance_techniques(
        model="muse-spark-1.3",
        harness_version="h_v1.1_canary",
        composition_runs=50,
        composition_interferences=2,
        integrity_evals=100,
        integrity_flags=22,
        visible_pass_rate=0.95,
        heldout_pass_rate=0.55,
        speculation_trials=300,
        speculation_accepted=210,
        speculation_mismatches=1,
        samples_per_task_k=2.1,
        cascade_trials=350,
        cascade_escalations=90,
        verification_runner_utilization=0.84,
        runner_utilization_increasing=True,
    )
    assert tripped["speculation_globally_enabled"] is False
    assert tripped["reward_hacking_alert"] is True
    assert tripped["canary_quarantined"] is True
    assert tripped["runner_capacity_action"] == "RECOMMEND_UPSTREAM_THROTTLE_OR_SCALE"


def test_provider_invoice_drift_and_pg_webhook_reconciliation_r47_3_r48_1_r48_3() -> None:
    """R47-3, R48-1..3: Daily invoice drift >1% alerts and classifies causes; PG webhooks handle duplicates & out-of-order refunds."""
    reconciler = BillingInvoiceAndWebhookReconciler(drift_alert_threshold=0.01)

    receipts = [
        {
            "provider": "meta",
            "source": "provider_billed",
            "provider_request_id": "req-1",
            "cost_micros": 100_000,
            "price_table_version": "pt_2026_10_v1",
        },
        {
            "provider": "meta",
            "source": "provider_billed",
            "provider_request_id": "req-2",
            "cost_micros": 100_000,
            "price_table_version": "pt_2026_09_old",
        },
        {
            "provider": "meta",
            "source": "provider_billed",
            "provider_request_id": "req-unbilled",
            "cost_micros": 5_000,
            "price_table_version": "pt_2026_10_v1",
        },
    ]
    invoice_lines = [
        {"provider": "meta", "provider_request_id": "req-1", "billed_cost_micros": 100_000},
        {"provider": "meta", "provider_request_id": "req-2", "billed_cost_micros": 115_000},
        {"provider": "meta", "provider_request_id": "req-missing-rcpt", "billed_cost_micros": 20_000},
    ]

    report = reconciler.reconcile_daily_provider_invoice(
        provider="meta",
        billing_date="2026-10-27",
        receipts=receipts,
        invoice_lines=invoice_lines,
        expected_price_table_version="pt_2026_10_v1",
    )
    assert report["alert_triggered"] is True
    assert report["drift_ratio"] > 0.01
    causes = {d["provider_request_id"]: d["cause"] for d in report["discrepancies"]}
    assert causes == {
        "req-2": "PRICE_TABLE_DRIFT",
        "req-missing-rcpt": "MISSING_RECEIPT",
        "req-unbilled": "UNBILLED_RECEIPT",
    }

    # Payment PG webhook out-of-order partial refund arriving BEFORE payment.succeeded + duplicate webhook
    partial_refund_wh = {
        "tenant_id": TENANT_ID,
        "webhook_id": "wh-refund-1",
        "event_type": "payment.partial_refunded",
        "transaction_id": "tx-900",
        "amount_micros": 300_000,
    }
    purchase_wh = {
        "tenant_id": TENANT_ID,
        "webhook_id": "wh-purchase-1",
        "event_type": "payment.succeeded",
        "transaction_id": "tx-900",
        "amount_micros": 1_000_000,
    }

    r1 = reconciler.ingest_payment_webhook(partial_refund_wh)
    assert r1["status"] == "BUFFERED_OUT_OF_ORDER"
    assert reconciler.tenant_credit_balance(TENANT_ID) == 0

    r2 = reconciler.ingest_payment_webhook(purchase_wh)
    assert r2["status"] == "APPLIED"
    # Both purchase (+1,000,000) and buffered partial refund (-300,000) are now applied -> 700,000
    assert reconciler.tenant_credit_balance(TENANT_ID) == 700_000

    # Duplicate deliveries of both webhooks do not change balance (R48-1: 0 duplicate charges/refunds)
    assert reconciler.ingest_payment_webhook(purchase_wh)["status"] == "DUPLICATE_IGNORED"
    assert reconciler.ingest_payment_webhook(partial_refund_wh)["status"] == "DUPLICATE_IGNORED"
    assert reconciler.tenant_credit_balance(TENANT_ID) == 700_000

    # Over-refund exceeding original payment is rejected
    with pytest.raises(GovernanceError) as exc_over:
        reconciler.ingest_payment_webhook(
            {
                "tenant_id": TENANT_ID,
                "webhook_id": "wh-refund-excess",
                "event_type": "payment.partial_refunded",
                "transaction_id": "tx-900",
                "amount_micros": 800_000,
            }
        )
    assert exc_over.value.code == "REFUND_EXCEEDS_PAYMENT"


def test_incident_state_machine_and_context_lifecycle_guards_cr17_cr22_cr24_cr69_r46_2() -> None:
    """Incident containment, CR-22 packet STALE on objective change, CR-24 flag OFF, CR-69 S11 layout, CR-17/R46-2 shred cascade."""
    gov = IncidentAndLifecycleGovernance()

    # 1. Incident state machine & supply-chain runbook
    gov.open_incident(incident_id="inc-1", kind="supply_chain", summary="suspicious transitive wheel")
    with pytest.raises(GovernanceError) as exc_jump:
        gov.advance_incident_phase("inc-1", "RECOVER")  # cannot skip TRIAGE and CONTAIN
    assert exc_jump.value.code == "ILLEGAL_INCIDENT_TRANSITION"

    gov.advance_incident_phase("inc-1", "TRIAGE")
    gov.advance_incident_phase("inc-1", "CONTAIN")
    assert gov.operator_kill_switch == {
        "merge_blocked": True,
        "deploy_blocked": True,
        "provider_adapters_blocked": True,
    }
    sc_inc = gov.execute_supply_chain_runbook("inc-1")
    assert tuple(sc_inc["supply_chain_steps_completed"]) == SUPPLY_CHAIN_RUNBOOK_STEPS

    gov.advance_incident_phase("inc-1", "RECOVER")
    assert gov.operator_kill_switch["merge_blocked"] is False

    # 2. CR-22: Objective version mutation marks task packets STALE, blocks approval, and forbids revival
    gov.register_task_packet(tenant_id=TENANT_ID, task_id="task-7", packet_id="pkt-v1", objective_version=1)
    gov.assert_packet_approvable(tenant_id=TENANT_ID, task_id="task-7", packet_id="pkt-v1")

    stale_res = gov.update_task_objective_version(tenant_id=TENANT_ID, task_id="task-7", new_objective_version=2)
    assert stale_res["staled_packets"] == ["pkt-v1"]

    with pytest.raises(GovernanceError) as exc_stale_app:
        gov.assert_packet_approvable(tenant_id=TENANT_ID, task_id="task-7", packet_id="pkt-v1")
    assert exc_stale_app.value.code == "PACKET_NOT_ACTIVE"

    with pytest.raises(GovernanceError) as exc_revive:
        gov.revive_packet(tenant_id=TENANT_ID, task_id="task-7", packet_id="pkt-v1")
    assert exc_revive.value.code == "STALE_PACKET_REVIVAL_FORBIDDEN"

    # 3. CR-24: Codec feature flag OFF returns RAW(POLICY_RAW_ONLY)
    raw_fallback = gov.encode_with_feature_flag(
        source_kind="json.api",
        raw_content='{"status": "ok"}',
        codec_feature_flag_enabled=False,
        encoder_fn=lambda _x: (_ for _ in ()).throw(AssertionError("must not call codec when flag is OFF")),
    )
    assert raw_fallback["representation"] == "RAW"
    assert raw_fallback["raw_fallback_reason"] == "POLICY_RAW_ONLY"

    # 4. CR-69: S11 cache breakpoint on L3 or tool_output/untrusted in cached prefix rejected
    with pytest.raises(GovernanceError) as exc_bp:
        gov.validate_s11_cache_placement({"cache_plan": {"breakpoints": [{"layer": "L3"}]}, "items": []})
    assert exc_bp.value.code == "S11_BREAKPOINT_ON_L3"

    with pytest.raises(GovernanceError) as exc_tool_prefix:
        gov.validate_s11_cache_placement(
            {
                "cache_plan": {"breakpoints": [{"layer": "L2"}]},
                "items": [{"layer": "L2", "item_kind": "tool_output", "trust_level": "trusted"}],
            }
        )
    assert exc_tool_prefix.value.code == "S11_TOOL_OUTPUT_IN_PREFIX"

    # 5. CR-17 & R46-2: Crypto-shredding deletion cascade (legal hold blocks, otherwise purges all derived artifacts)
    gov.register_blob_with_derivations(
        tenant_id=TENANT_ID,
        blob_id="blob-hold",
        dek_id="dek-hold",
        evidence_refs=["ef_ref_hold111111111111"],
        dependent_packet_ids=["pkt-hold"],
        search_index_ids=["idx-1"],
        embedding_ids=["emb-1"],
        playbook_lesson_ids=["lesson-1"],
        legal_hold=True,
    )
    with pytest.raises(GovernanceError) as exc_hold:
        gov.shred_blob_and_cascade(tenant_id=TENANT_ID, blob_id="blob-hold")
    assert exc_hold.value.code == "LEGAL_HOLD_ACTIVE"

    gov.register_blob_with_derivations(
        tenant_id=TENANT_ID,
        blob_id="blob-del",
        dek_id="dek-del",
        evidence_refs=["ef_ref_del1111111111111", "ef_ref_del2222222222222"],
        dependent_packet_ids=["pkt-del-1"],
        search_index_ids=["idx-a", "idx-b"],
        embedding_ids=["emb-a"],
        playbook_lesson_ids=["lesson-a"],
        legal_hold=False,
    )
    shred_res = gov.shred_blob_and_cascade(tenant_id=TENANT_ID, blob_id="blob-del")
    assert shred_res["status"] == "SHREDDED"
    assert shred_res["dek_destroyed"] is True
    assert shred_res["derived_remaining_count"] == 0
    assert shred_res["revoked_packets"] == ["pkt-del-1"]
    assert shred_res["backup_expiration_schedule"]["encrypted_backup_unreadable_via_dek_shred"] is True


def test_milestone_and_ga_release_evidence_package_r49_1_r49_5_r50_1() -> None:
    """R49-1, R49-5, R50-1: Release Evidence Package enforces muse-spark-1.3, 5 harness modules, holdout >= 200, and 100% hygiene."""
    gov = IncidentAndLifecycleGovernance()
    harness_manifest = {
        "variants": {"T": "t_v1", "C": "c_v1", "S": "s_v1", "M": "m_v1", "W": "w_v1"},
        "config_hash": "cfg_sha_001",
    }

    # Reject non-Muse default model
    with pytest.raises(GovernanceError) as exc_model:
        gov.build_and_verify_release_package(
            milestone="M0",
            commit_sha="8f2323c",
            image_digest="sha256:1234567890abcdef",
            harness_version_manifest=harness_manifest,
            default_model="other-model",
            eval_set_sha="eval_sha_1",
            policy_sha="pol_sha_1",
            oracle_human_holdout_count=220,
            sandbox_hygiene_pass_rate=1.0,
            design_targets={"speedup_ci_lower": 1.5},
            measured_values={"speedup_ci_lower": 1.62},
            checklist_evidence_links={"sql_96": "docs/LOCAL_POSTGRES_VALIDATION.md"},
        )
    assert exc_model.value.code == "MODEL_DEFAULT_VIOLATION"

    # Reject oracle holdout < 200 (R49-5, D-054)
    with pytest.raises(GovernanceError) as exc_holdout:
        gov.build_and_verify_release_package(
            milestone="M0",
            commit_sha="8f2323c",
            image_digest="sha256:1234567890abcdef",
            harness_version_manifest=harness_manifest,
            default_model="muse-spark-1.3",
            eval_set_sha="eval_sha_1",
            policy_sha="pol_sha_1",
            oracle_human_holdout_count=150,
            sandbox_hygiene_pass_rate=1.0,
            design_targets={"speedup_ci_lower": 1.5},
            measured_values={"speedup_ci_lower": 1.62},
            checklist_evidence_links={"sql_96": "docs/LOCAL_POSTGRES_VALIDATION.md"},
        )
    assert exc_holdout.value.code == "ORACLE_HOLDOUT_UNDER_200"

    pkg = gov.build_and_verify_release_package(
        milestone="M0",
        commit_sha="8f2323c",
        image_digest="sha256:1234567890abcdef",
        harness_version_manifest=harness_manifest,
        default_model="muse-spark-1.3",
        eval_set_sha="eval_sha_1",
        policy_sha="pol_sha_1",
        oracle_human_holdout_count=240,
        sandbox_hygiene_pass_rate=1.0,
        design_targets={"speedup_ci_lower": 1.5, "api_availability_pct": 99.9},
        measured_values={"speedup_ci_lower": 1.68, "api_availability_pct": 99.96},
        checklist_evidence_links={
            "sql_96": "docs/LOCAL_POSTGRES_VALIDATION.md",
            "hygiene_audit": "docs/EVAL_RUNNER_AND_PREFLIGHT.md",
        },
    )
    assert pkg["verified"] is True
    assert pkg["default_model"] == "muse-spark-1.3"
    assert len(pkg["package_sha256"]) == 64
