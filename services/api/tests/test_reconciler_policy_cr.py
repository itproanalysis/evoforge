"""Acceptance tests for Reconciler Policy (CR-13, CR-39, CR-40, CR-47, zero-cost settlement, and UNKNOWN reconciler job)."""
from __future__ import annotations

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evoforge import ledger as mem_ledger  # noqa: E402
from evoforge.reconciler_policy import (  # noqa: E402
    IllegalSideEffectTransition,
    LedgerConstraintError,
    LedgerReversalError,
    ProviderLookupOutcome,
    ReconcilerLedger,
    ReservationPolicyError,
    UnknownReservationReconciler,
)

TENANT_ID = "11111111-1111-4111-8111-111111111111"
PROJECT_ID = "22222222-2222-4222-8222-222222222222"
PACKET_ID = "33333333-3333-4333-8333-333333333333"
PERIOD = "2026-10-01"


def _make_receipt(
    *,
    call_id: str,
    customer_price_micros: int,
    cost_micros: int = 500,
    source: str = "provider_billed",
    receipt_id: str | None = None,
    packet_id: str = PACKET_ID,
    provider_request_id: str = "req_meta_001",
) -> dict:
    doc = {
        "schema_version": "provider-usage-receipt/v1",
        "receipt_id": receipt_id or str(uuid.uuid4()),
        "tenant_id": TENANT_ID,
        "project_id": PROJECT_ID,
        "packet_id": packet_id,
        "call_id": call_id,
        "reservation_key": call_id,
        "call_purpose": "task_turn",
        "provider": "meta",
        "model": "muse-spark-1.3",
        "source": source,
        "billing_owner": "platform",
        "tokens": {
            "uncached_input": 1200,
            "cache_write": 0,
            "cache_read": 800,
            "output": 400,
        },
        "cost_micros": cost_micros,
        "customer_price_micros": customer_price_micros,
        "currency": "USD",
        "price_table_version": "pt_v1",
        "recorded_at": "2026-10-27T12:00:00Z",
    }
    if source == "provider_billed":
        doc["provider_request_id"] = provider_request_id
        doc["raw_usage_fields"] = {"prompt_tokens": 2000, "completion_tokens": 400}
    return doc


def test_zero_cost_settlement_closes_reservation_without_fake_charge() -> None:
    """Zero-cost (`customer_price_micros == 0`) settlement closes reservation and writes a 0-micro adjustment row."""
    eng = ReconcilerLedger()
    eng.set_project_budget(TENANT_ID, PROJECT_ID, PERIOD, 10_000_000)
    eng.grant_credit(TENANT_ID, 20_000_000, idempotency_key="grant:init")

    call_id = str(uuid.uuid4())
    eng.reserve_cost(TENANT_ID, PROJECT_ID, PERIOD, call_id, 2_500)
    assert eng.tenant_open_reserved_micros(TENANT_ID) == 2_500
    assert eng.project_used_micros(TENANT_ID, PROJECT_ID, PERIOD) == 2_500

    doc = _make_receipt(call_id=call_id, customer_price_micros=0, cost_micros=0)
    rec = eng.record_receipt(doc)
    settled = eng.settle_receipt(TENANT_ID, PROJECT_ID, rec.receipt_id)

    assert settled["zero_cost"] is True
    assert settled["entry_kind"] == "adjustment"
    assert settled["customer_micros"] == 0
    assert settled["actual_micros"] == 0
    assert settled["overrun"] is False

    # Open reservation hold is released cleanly; credit balance is untouched (still 20_000_000)
    assert eng.tenant_open_reserved_micros(TENANT_ID) == 0
    assert eng.project_used_micros(TENANT_ID, PROJECT_ID, PERIOD) == 0
    assert eng.credit_balance(TENANT_ID) == 20_000_000

    # Direct `model_usage` with 0 customer_micros is still strictly forbidden by ledger_sign
    with pytest.raises(LedgerConstraintError):
        eng._append_ledger_entry(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            entry_kind="model_usage",
            customer_micros=0,
            provider_cost_micros=0,
            receipt_id=rec.receipt_id,
            reverses_entry_id=None,
            idempotency_key="bad:zero-model-usage",
            price_table_version="pt_v1",
        )


def test_estimated_to_billed_reconciliation_and_single_reversal_cr13_cr40() -> None:
    """CR-13 & CR-40: estimated receipts are excluded from KPIs and reconciled via single adjustment reversal."""
    eng = ReconcilerLedger()
    eng.set_project_budget(TENANT_ID, PROJECT_ID, PERIOD, 50_000)
    eng.grant_credit(TENANT_ID, 100_000, idempotency_key="grant:100k")

    call_est = str(uuid.uuid4())
    eng.reserve_cost(TENANT_ID, PROJECT_ID, PERIOD, call_est, 5_000)
    est_doc = _make_receipt(call_id=call_est, customer_price_micros=4_000, cost_micros=3_200, source="estimated")
    est_rec = eng.record_receipt(est_doc)
    est_settled = eng.settle_receipt(TENANT_ID, PROJECT_ID, est_rec.receipt_id)

    # CR-13: source="estimated" is excluded from verified KPIs even after provisional settlement
    kpi_before = eng.aggregate_verified_kpi(TENANT_ID, PROJECT_ID)
    assert kpi_before["eligible_receipt_count"] == 0
    assert kpi_before["excluded_estimated_count"] == 1
    assert eng.credit_balance(TENANT_ID) == 100_000 - 4_000

    # Reconcile estimated (4_000) -> provider_billed (3_100)
    billed_doc = _make_receipt(
        call_id=call_est,
        customer_price_micros=3_100,
        cost_micros=2_500,
        source="provider_billed",
        provider_request_id="req_final_01",
    )
    recon = eng.reconcile_estimated_to_billed(billed_doc)
    assert recon["estimated_customer_micros"] == 4_000
    assert recon["billed_customer_micros"] == 3_100
    assert recon["net_delta_micros"] == -900
    assert recon["reversal_entry_id"] is not None

    # Balance reflects exact final billed amount: 100_000 - 4_000 + 4_000 - 3_100 = 96_900
    assert eng.credit_balance(TENANT_ID) == 96_900
    assert eng.project_used_micros(TENANT_ID, PROJECT_ID, PERIOD) == 3_100

    # CR-40: Reversing the already-reversed estimated entry a second time is rejected
    with pytest.raises(LedgerReversalError, match="entry already reversed"):
        eng.reverse_ledger_entry(TENANT_ID, est_settled["ledger_entry_id"])

    # CR-40: Reversal with wrong sign/amount or non-adjustment kind is rejected
    with pytest.raises(LedgerReversalError, match="reversals must be adjustment entries"):
        eng.reverse_ledger_entry(TENANT_ID, recon["billed_ledger_entry_id"], entry_kind="refund")
    with pytest.raises(LedgerReversalError, match="reversal must negate the original amount"):
        eng.reverse_ledger_entry(TENANT_ID, recon["billed_ledger_entry_id"], customer_micros=100)

    # CR-13: Now the provider_billed receipt counts toward verified KPIs
    kpi_after = eng.aggregate_verified_kpi(TENANT_ID, PROJECT_ID)
    assert kpi_after["eligible_receipt_count"] == 1
    assert kpi_after["total_customer_price_micros"] == 3_100


def test_side_effect_intent_cr47_and_unknown_reconciler_job_cr39() -> None:
    """CR-39 & CR-47: UNKNOWN cannot retry directly; batch reconciler settles overrun/zero-cost and releases unbilled."""
    eng = ReconcilerLedger()
    eng.set_project_budget(TENANT_ID, PROJECT_ID, PERIOD, 50_000)
    eng.grant_credit(TENANT_ID, 100_000, idempotency_key="grant:cr47")

    call_overrun = str(uuid.uuid4())
    call_unbilled = str(uuid.uuid4())
    call_pending = str(uuid.uuid4())

    eng.reserve_cost(TENANT_ID, PROJECT_ID, PERIOD, call_overrun, 2_000)
    eng.reserve_cost(TENANT_ID, PROJECT_ID, PERIOD, call_unbilled, 3_000)
    eng.reserve_cost(TENANT_ID, PROJECT_ID, PERIOD, call_pending, 1_500)

    intent_overrun = eng.mark_call_unknown(TENANT_ID, PROJECT_ID, call_overrun)
    intent_unbilled = eng.mark_call_unknown(TENANT_ID, PROJECT_ID, call_unbilled)
    intent_pending = eng.mark_call_unknown(TENANT_ID, PROJECT_ID, call_pending)

    # CR-47: Retrying directly from UNKNOWN_EXTERNAL_OUTCOME -> SENT is forbidden
    with pytest.raises(IllegalSideEffectTransition, match="reconcile UNKNOWN before retry"):
        eng.transition_intent(TENANT_ID, intent_overrun.intent_id, "SENT")

    # Run automated UNKNOWN reservation reconciliation job
    worker = UnknownReservationReconciler(eng)

    def oracle(t_id: str, p_id: str, req_key: str) -> ProviderLookupOutcome:
        if req_key == call_overrun:
            # CR-39: Actual cost (3_500) > reserved (2_000) -> settles and marks overrun=True
            return ProviderLookupOutcome(
                status="BILLED",
                receipt_document=_make_receipt(
                    call_id=call_overrun,
                    customer_price_micros=3_500,
                    cost_micros=2_800,
                    provider_request_id="req_overrun_1",
                ),
            )
        if req_key == call_unbilled:
            return ProviderLookupOutcome(status="NOT_ACCEPTED", reason="provider never received request")
        return ProviderLookupOutcome(status="STILL_UNKNOWN", reason="provider lookup timeout")

    report = worker.reconcile_micros_batch(oracle)
    assert report["scanned"] == 3
    assert len(report["settled"]) == 1
    assert report["settled"][0]["call_id"] == call_overrun
    assert report["settled"][0]["overrun"] is True
    assert report["released"] == [call_unbilled]
    assert report["still_unknown"] == [call_pending]

    # Unbilled call is now FAILED and RELEASED; its intent can legally transition FAILED -> SENT for retry
    assert eng.get_reservation(TENANT_ID, PROJECT_ID, call_unbilled).status == "RELEASED"
    retried = eng.transition_intent(TENANT_ID, intent_unbilled.intent_id, "SENT")
    assert retried.status == "SENT"

    # Still-unknown call remains locked and still blocks direct retry
    assert eng.get_reservation(TENANT_ID, PROJECT_ID, call_pending).status == "RESERVED"
    with pytest.raises(IllegalSideEffectTransition):
        eng.transition_intent(TENANT_ID, intent_pending.intent_id, "SENT")


def test_in_memory_unknown_reconciler_job() -> None:
    """In-memory `evoforge.ledger` UNKNOWN reservations are swept and settled/refunded by `UnknownReservationReconciler`."""
    mem_ledger.reset()
    mem_ledger.configure({"proj_demo": 1000})
    r_billed = mem_ledger.reserve(200, "proj_demo")
    r_refund = mem_ledger.reserve(150, "proj_demo")
    r_wait = mem_ledger.reserve(100, "proj_demo")

    mem_ledger.mark_unknown(r_billed, "timeout_1")
    mem_ledger.mark_unknown(r_refund, "timeout_2")
    mem_ledger.mark_unknown(r_wait, "timeout_3")

    def mem_oracle(rid: str) -> ProviderLookupOutcome:
        if rid == r_billed:
            return ProviderLookupOutcome(status="BILLED", billed_cents=180, provider_request_id="req_mem_1")
        if rid == r_refund:
            return ProviderLookupOutcome(status="NOT_ACCEPTED")
        return ProviderLookupOutcome(status="STILL_UNKNOWN")

    res = UnknownReservationReconciler.reconcile_in_memory_unknowns("proj_demo", mem_oracle)
    assert res["scanned"] == 3
    assert len(res["settled"]) == 1
    assert res["refunded"] == [r_refund]
    assert res["still_unknown"] == [r_wait]

    snap = mem_ledger.snapshot("proj_demo")
    assert snap["spent_cents"] == 180
    assert snap["reserved_cents"] == 100
    assert snap["unknown_reservations"] == [r_wait]
    mem_ledger.reset()
