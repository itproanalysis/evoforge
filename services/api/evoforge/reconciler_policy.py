"""Zero-cost settlement, estimated-to-billed receipt reconciliation, and UNKNOWN reservation reconciler job.

Closes the remaining billing & reconciliation policy items in:
  * docs/DEVELOPMENT_STATUS.md (lines 87, 99):
    - Automated job to settle/refund UNKNOWN reservations via receipt reconciliation.
    - Canonical zero-cost (0 micro-USD / 0 cents) settlement without fake charge/refund workarounds.
    - Estimated receipt -> provider_billed receipt correction & single-reversal reconciliation policy.
  * docs/RECEIPT_PERSISTENCE.md (lines 53, 58, 86-88)
  * docs/evoforge-v4.2/contracts/Acceptance_Test_Matrix.md:
    - CR-13: source="estimated" receipts excluded from official cost/savings KPIs.
    - CR-39: actual > reserved settles provider payment and sets overrun=true.
    - CR-40: usage_ledger append-only; corrections via adjustment(reverses_entry_id) once only.
    - CR-47: UNKNOWN_EXTERNAL_OUTCOME cannot transition directly to SENT; must reconcile first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Callable
import uuid

from evoforge import ledger as mem_ledger
from evoforge.postgres_receipts import ReceiptInvalid, canonical_receipt

VALID_INTENT_KINDS = frozenset({
    "provider.call",
    "github.create_pr",
    "github.merge",
    "billing.charge",
})

VALID_INTENT_STATUSES = frozenset({
    "RESERVED",
    "SENT",
    "CONFIRMED",
    "UNKNOWN_EXTERNAL_OUTCOME",
    "FAILED",
    "COMPENSATED",
})

ALLOWED_INTENT_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("RESERVED", "SENT"),
    ("SENT", "CONFIRMED"),
    ("SENT", "FAILED"),
    ("SENT", "UNKNOWN_EXTERNAL_OUTCOME"),
    ("UNKNOWN_EXTERNAL_OUTCOME", "CONFIRMED"),
    ("UNKNOWN_EXTERNAL_OUTCOME", "FAILED"),
    ("FAILED", "SENT"),
    ("CONFIRMED", "COMPENSATED"),
})

POSITIVE_LEDGER_KINDS = frozenset({"credit_purchase", "credit_grant", "refund"})
NEGATIVE_LEDGER_KINDS = frozenset({"model_usage", "runner_minutes", "storage", "subscription_fee"})
ALL_LEDGER_KINDS = POSITIVE_LEDGER_KINDS | NEGATIVE_LEDGER_KINDS | {"adjustment"}


class ReconcilerError(RuntimeError):
    """Base error for reconciliation and ledger policy violations."""


class IllegalSideEffectTransition(ReconcilerError):
    """Raised when a side-effect intent violates CR-47 transition rules."""


class LedgerConstraintError(ReconcilerError):
    """Raised when an operation violates core.usage_ledger constraints."""


class LedgerReversalError(LedgerConstraintError):
    """Raised when a reversal violates core.enforce_reversal (CR-40)."""


class ReservationPolicyError(ReconcilerError):
    """Raised when a reservation or receipt settlement violates policy."""


def _require_non_neg_int(val: object, name: str) -> int:
    if isinstance(val, bool) or not isinstance(val, int) or val < 0:
        raise ValueError(f"{name} must be a non-negative int")
    return val


def _require_pos_int(val: object, name: str) -> int:
    if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
        raise ValueError(f"{name} must be a positive int")
    return val


def _require_signed_int(val: object, name: str) -> int:
    if isinstance(val, bool) or not isinstance(val, int):
        raise ValueError(f"{name} must be an int")
    return val


@dataclass(frozen=True)
class SideEffectIntentRecord:
    tenant_id: str
    intent_id: str
    kind: str
    idempotency_key: str
    status: str
    external_ref: str | None = None


@dataclass(frozen=True)
class CostReservationRecord:
    tenant_id: str
    project_id: str
    request_key: str
    period_start: str
    reserved_micros: int
    actual_micros: int | None
    status: str  # RESERVED | COMMITTED | RELEASED
    overrun: bool
    created_at: float


@dataclass(frozen=True)
class UsageLedgerEntry:
    tenant_id: str
    entry_id: str
    project_id: str | None
    entry_kind: str
    customer_micros: int
    provider_cost_micros: int
    receipt_id: str | None
    reverses_entry_id: str | None
    idempotency_key: str
    price_table_version: str
    recorded_at: float


@dataclass(frozen=True)
class StoredReceiptRecord:
    receipt_id: str
    tenant_id: str
    project_id: str
    call_id: str
    packet_id: str
    source: str  # provider_billed | estimated
    cost_micros: int
    customer_price_micros: int
    provider_request_id: str | None
    price_table_version: str
    sha256: str
    document: dict
    superseded_by_receipt_id: str | None = None
    ledger_entry_id: str | None = None


@dataclass(frozen=True)
class ProviderLookupOutcome:
    """Result returned by a provider receipt lookup oracle during UNKNOWN reconciliation."""

    status: str  # "BILLED" | "NOT_ACCEPTED" | "STILL_UNKNOWN"
    receipt_document: dict | None = None
    billed_cents: int | None = None
    provider_request_id: str | None = None
    reason: str = ""


class ReconcilerLedger:
    """Canonical micro-USD reservation, receipt, and append-only ledger policy engine.

    Enforces exact parity with `core.cost_reservations`, `core.usage_ledger`,
    `core.side_effect_intents`, and `ctx.provider_usage_receipts`, while adding:
      1. Canonical zero-cost (`0` micro-USD) settlement without fake charges/refunds.
      2. Estimated-to-billed (`estimated` -> `provider_billed`) single-reversal correction.
      3. Automated UNKNOWN reservation reconciliation sweep (`CR-39`, `CR-47`).
      4. Official KPI filtering that excludes `source="estimated"` receipts (`CR-13`).
    """

    def __init__(self) -> None:
        self._budgets: dict[tuple[str, str, str], int] = {}
        self._reservations: dict[tuple[str, str, str], CostReservationRecord] = {}
        self._intents: dict[tuple[str, str], SideEffectIntentRecord] = {}
        self._intents_by_key: dict[tuple[str, str, str], str] = {}
        self._ledger: list[UsageLedgerEntry] = []
        self._receipts: dict[str, StoredReceiptRecord] = {}
        self._active_receipt_by_call: dict[tuple[str, str, str], str] = {}
        self._receipt_history_by_call: dict[tuple[str, str, str], list[str]] = {}

    # ------------------------------------------------------------------ setup & credit balance
    def set_project_budget(self, tenant_id: str, project_id: str, period_start: str, cap_micros: int) -> None:
        _require_non_neg_int(cap_micros, "cap_micros")
        self._budgets[(tenant_id, project_id, period_start)] = cap_micros

    def grant_credit(
        self,
        tenant_id: str,
        customer_micros: int,
        *,
        idempotency_key: str,
        entry_kind: str = "credit_purchase",
        price_table_version: str = "pt_v1",
    ) -> UsageLedgerEntry:
        if entry_kind not in ("credit_purchase", "credit_grant"):
            raise LedgerConstraintError(f"grant_credit requires credit_purchase or credit_grant, got {entry_kind}")
        _require_pos_int(customer_micros, "customer_micros")
        return self._append_ledger_entry(
            tenant_id=tenant_id,
            project_id=None,
            entry_kind=entry_kind,
            customer_micros=customer_micros,
            provider_cost_micros=0,
            receipt_id=None,
            reverses_entry_id=None,
            idempotency_key=idempotency_key,
            price_table_version=price_table_version,
        )

    def credit_balance(self, tenant_id: str) -> int:
        return sum(e.customer_micros for e in self._ledger if e.tenant_id == tenant_id)

    def project_used_micros(self, tenant_id: str, project_id: str, period_start: str) -> int:
        total = 0
        for r in self._reservations.values():
            if r.tenant_id == tenant_id and r.project_id == project_id and r.period_start == period_start:
                if r.status == "RESERVED":
                    total += r.reserved_micros
                elif r.status == "COMMITTED":
                    total += r.actual_micros or 0
        return total

    def tenant_open_reserved_micros(self, tenant_id: str) -> int:
        return sum(
            r.reserved_micros
            for r in self._reservations.values()
            if r.tenant_id == tenant_id and r.status == "RESERVED"
        )

    # ------------------------------------------------------------------ side-effect intents (CR-47)
    def create_intent(
        self,
        tenant_id: str,
        kind: str,
        idempotency_key: str,
        *,
        intent_id: str | None = None,
    ) -> SideEffectIntentRecord:
        if kind not in VALID_INTENT_KINDS:
            raise IllegalSideEffectTransition(f"invalid side-effect kind: {kind}")
        dedup = (tenant_id, kind, idempotency_key)
        if dedup in self._intents_by_key:
            return self._intents[(tenant_id, self._intents_by_key[dedup])]
        iid = intent_id or str(uuid.uuid4())
        rec = SideEffectIntentRecord(
            tenant_id=tenant_id,
            intent_id=iid,
            kind=kind,
            idempotency_key=idempotency_key,
            status="RESERVED",
            external_ref=None,
        )
        self._intents[(tenant_id, iid)] = rec
        self._intents_by_key[dedup] = iid
        return rec

    def transition_intent(
        self,
        tenant_id: str,
        intent_id: str,
        new_status: str,
        *,
        external_ref: str | None = None,
    ) -> SideEffectIntentRecord:
        key = (tenant_id, intent_id)
        if key not in self._intents:
            raise KeyError(f"unknown intent {intent_id}")
        cur = self._intents[key]
        if new_status not in VALID_INTENT_STATUSES:
            raise IllegalSideEffectTransition(f"invalid intent status: {new_status}")
        if cur.status == new_status and (external_ref is None or external_ref == cur.external_ref):
            return cur
        if (cur.status, new_status) not in ALLOWED_INTENT_TRANSITIONS:
            raise IllegalSideEffectTransition(
                f"illegal side-effect transition {cur.status} -> {new_status} (reconcile UNKNOWN before retry)"
            )
        resolved_ref = external_ref if external_ref is not None else cur.external_ref
        if new_status == "CONFIRMED" and (not isinstance(resolved_ref, str) or not resolved_ref.strip()):
            raise IllegalSideEffectTransition("CONFIRMED intent requires non-empty external_ref")
        updated = SideEffectIntentRecord(
            tenant_id=cur.tenant_id,
            intent_id=cur.intent_id,
            kind=cur.kind,
            idempotency_key=cur.idempotency_key,
            status=new_status,
            external_ref=resolved_ref,
        )
        self._intents[key] = updated
        return updated

    def get_intent(self, tenant_id: str, intent_id: str) -> SideEffectIntentRecord:
        return self._intents[(tenant_id, intent_id)]

    # ------------------------------------------------------------------ cost reservations (CR-39)
    def reserve_cost(
        self,
        tenant_id: str,
        project_id: str,
        period_start: str,
        request_key: str,
        amount_micros: int,
    ) -> CostReservationRecord:
        _require_pos_int(amount_micros, "amount_micros")
        rkey = (tenant_id, project_id, request_key)
        if rkey in self._reservations:
            return self._reservations[rkey]
        bkey = (tenant_id, project_id, period_start)
        if bkey not in self._budgets:
            raise ReservationPolicyError("BUDGET_MISSING")
        cap = self._budgets[bkey]
        used = self.project_used_micros(tenant_id, project_id, period_start)
        if used + amount_micros > cap:
            raise ReservationPolicyError(f"BUDGET_EXCEEDED project cap {cap} used {used} request {amount_micros}")
        open_res = self.tenant_open_reserved_micros(tenant_id)
        balance = self.credit_balance(tenant_id)
        if balance - open_res < amount_micros:
            raise ReservationPolicyError(
                f"CREDIT_EXHAUSTED balance {balance} open reservations {open_res} request {amount_micros}"
            )
        rec = CostReservationRecord(
            tenant_id=tenant_id,
            project_id=project_id,
            request_key=request_key,
            period_start=period_start,
            reserved_micros=amount_micros,
            actual_micros=None,
            status="RESERVED",
            overrun=False,
            created_at=time.time(),
        )
        self._reservations[rkey] = rec
        self.create_intent(tenant_id, "provider.call", request_key)
        return rec

    def mark_call_sent(self, tenant_id: str, project_id: str, request_key: str) -> SideEffectIntentRecord:
        rkey = (tenant_id, project_id, request_key)
        if rkey not in self._reservations or self._reservations[rkey].status != "RESERVED":
            raise ReservationPolicyError(f"reservation {request_key} is not open RESERVED")
        iid = self._intents_by_key[(tenant_id, "provider.call", request_key)]
        return self.transition_intent(tenant_id, iid, "SENT")

    def mark_call_unknown(self, tenant_id: str, project_id: str, request_key: str) -> SideEffectIntentRecord:
        rkey = (tenant_id, project_id, request_key)
        if rkey not in self._reservations or self._reservations[rkey].status != "RESERVED":
            raise ReservationPolicyError(f"reservation {request_key} is not open RESERVED")
        iid = self._intents_by_key[(tenant_id, "provider.call", request_key)]
        cur = self._intents[(tenant_id, iid)]
        if cur.status == "RESERVED":
            self.transition_intent(tenant_id, iid, "SENT")
        return self.transition_intent(tenant_id, iid, "UNKNOWN_EXTERNAL_OUTCOME")

    def release_not_accepted(self, tenant_id: str, project_id: str, request_key: str) -> CostReservationRecord:
        """Release a reservation whose provider call was never accepted (or confirmed unbilled in reconciliation)."""
        rkey = (tenant_id, project_id, request_key)
        if rkey not in self._reservations:
            raise KeyError(f"unknown reservation {request_key}")
        if rkey in self._active_receipt_by_call:
            raise ReservationPolicyError(
                f"cannot release reservation {request_key}: receipt already recorded"
            )
        cur = self._reservations[rkey]
        if cur.status != "RESERVED":
            raise ReservationPolicyError(f"reservation {request_key} is already {cur.status}")
        iid = self._intents_by_key.get((tenant_id, "provider.call", request_key))
        if iid is not None:
            intent = self._intents[(tenant_id, iid)]
            if intent.status == "SENT" or intent.status == "UNKNOWN_EXTERNAL_OUTCOME":
                self.transition_intent(tenant_id, iid, "FAILED")
        released = CostReservationRecord(
            tenant_id=cur.tenant_id,
            project_id=cur.project_id,
            request_key=cur.request_key,
            period_start=cur.period_start,
            reserved_micros=cur.reserved_micros,
            actual_micros=None,
            status="RELEASED",
            overrun=False,
            created_at=cur.created_at,
        )
        self._reservations[rkey] = released
        return released

    # ------------------------------------------------------------------ receipts & zero-cost settlement
    def record_receipt(
        self,
        document: dict,
        *,
        price_table_version: str = "pt_v1",
        allow_supersede_estimated: bool = False,
    ) -> StoredReceiptRecord:
        validated, digest = canonical_receipt(document)
        tenant_id = validated["tenant_id"]
        project_id = validated["project_id"]
        call_id = validated["call_id"]
        receipt_id = validated["receipt_id"]
        rkey = (tenant_id, project_id, call_id)
        if rkey not in self._reservations:
            raise ReservationPolicyError(f"unknown reservation for call_id {call_id}")
        res = self._reservations[rkey]
        if res.status == "RELEASED":
            raise ReservationPolicyError(f"cannot record receipt for RELEASED reservation {call_id}")

        if receipt_id in self._receipts:
            existing = self._receipts[receipt_id]
            if existing.sha256 != digest:
                raise ReceiptInvalid("conflicting receipt document for existing receipt_id")
            return existing

        active_id = self._active_receipt_by_call.get(rkey)
        if active_id is not None:
            active = self._receipts[active_id]
            if not allow_supersede_estimated:
                raise ReservationPolicyError(
                    f"call {call_id} already has active receipt {active_id}; use reconcile_estimated_to_billed"
                )
            if active.source != "estimated" or validated["source"] != "provider_billed":
                raise ReservationPolicyError(
                    "only an active source='estimated' receipt can be superseded by source='provider_billed'"
                )

        rec = StoredReceiptRecord(
            receipt_id=receipt_id,
            tenant_id=tenant_id,
            project_id=project_id,
            call_id=call_id,
            packet_id=validated["packet_id"],
            source=validated["source"],
            cost_micros=validated["cost_micros"],
            customer_price_micros=validated["customer_price_micros"],
            provider_request_id=validated.get("provider_request_id"),
            price_table_version=price_table_version,
            sha256=digest,
            document=validated,
            superseded_by_receipt_id=None,
            ledger_entry_id=None,
        )
        self._receipts[receipt_id] = rec
        self._active_receipt_by_call[rkey] = receipt_id
        self._receipt_history_by_call.setdefault(rkey, []).append(receipt_id)
        return rec

    def settle_receipt(self, tenant_id: str, project_id: str, receipt_id: str) -> dict:
        """Settle an open reservation using a stored canonical receipt (supports >0 and 0 micro-USD).

        For `customer_price_micros > 0`:
          - Commits `core.cost_reservations` (`actual_micros = customer_price_micros`, `overrun = actual > reserved`)
          - Appends `core.usage_ledger` row with `entry_kind = 'model_usage'` and `customer_micros = -customer_price_micros`
        For `customer_price_micros == 0` (zero-cost settlement policy):
          - Commits `core.cost_reservations` (`actual_micros = 0`, `overrun = False`), releasing the open hold
          - Appends `core.usage_ledger` row with `entry_kind = 'adjustment'`, `customer_micros = 0`, `reverses_entry_id = None`
            (preserving full receipt linkage without violating `ledger_sign` or creating fake charges/refunds).
        """
        if receipt_id not in self._receipts:
            raise KeyError(f"unknown receipt {receipt_id}")
        rec = self._receipts[receipt_id]
        if rec.tenant_id != tenant_id or rec.project_id != project_id:
            raise ReservationPolicyError("receipt scope mismatch")
        if rec.superseded_by_receipt_id is not None:
            raise ReservationPolicyError(f"receipt {receipt_id} was superseded by {rec.superseded_by_receipt_id}")
        if rec.ledger_entry_id is not None:
            entry = next(e for e in self._ledger if e.entry_id == rec.ledger_entry_id)
            res = self._reservations[(tenant_id, project_id, rec.call_id)]
            return {
                "receipt_id": receipt_id,
                "call_id": rec.call_id,
                "ledger_entry_id": entry.entry_id,
                "entry_kind": entry.entry_kind,
                "customer_micros": entry.customer_micros,
                "reserved_micros": res.reserved_micros,
                "actual_micros": res.actual_micros,
                "overrun": res.overrun,
                "zero_cost": rec.customer_price_micros == 0,
            }

        rkey = (tenant_id, project_id, rec.call_id)
        res = self._reservations[rkey]
        if res.status != "RESERVED":
            raise ReservationPolicyError(f"reservation {rec.call_id} not open (status={res.status})")

        iid = self._intents_by_key.get((tenant_id, "provider.call", rec.call_id))
        if iid is not None:
            intent = self._intents[(tenant_id, iid)]
            if intent.status == "RESERVED":
                self.transition_intent(tenant_id, iid, "SENT")
            ext_ref = rec.provider_request_id or f"receipt:{rec.receipt_id}"
            self.transition_intent(tenant_id, iid, "CONFIRMED", external_ref=ext_ref)

        actual = rec.customer_price_micros
        overrun = actual > res.reserved_micros
        committed = CostReservationRecord(
            tenant_id=res.tenant_id,
            project_id=res.project_id,
            request_key=res.request_key,
            period_start=res.period_start,
            reserved_micros=res.reserved_micros,
            actual_micros=actual,
            status="COMMITTED",
            overrun=overrun,
            created_at=res.created_at,
        )
        self._reservations[rkey] = committed

        if actual > 0:
            entry = self._append_ledger_entry(
                tenant_id=tenant_id,
                project_id=project_id,
                entry_kind="model_usage",
                customer_micros=-actual,
                provider_cost_micros=rec.cost_micros,
                receipt_id=rec.receipt_id,
                reverses_entry_id=None,
                idempotency_key=f"settle:{rec.call_id}",
                price_table_version=rec.price_table_version,
            )
        else:
            entry = self._append_ledger_entry(
                tenant_id=tenant_id,
                project_id=project_id,
                entry_kind="adjustment",
                customer_micros=0,
                provider_cost_micros=rec.cost_micros,
                receipt_id=rec.receipt_id,
                reverses_entry_id=None,
                idempotency_key=f"settle:{rec.call_id}",
                price_table_version=rec.price_table_version,
            )

        self._receipts[receipt_id] = StoredReceiptRecord(
            **{**rec.__dict__, "ledger_entry_id": entry.entry_id}
        )
        return {
            "receipt_id": receipt_id,
            "call_id": rec.call_id,
            "ledger_entry_id": entry.entry_id,
            "entry_kind": entry.entry_kind,
            "customer_micros": entry.customer_micros,
            "reserved_micros": committed.reserved_micros,
            "actual_micros": committed.actual_micros,
            "overrun": committed.overrun,
            "zero_cost": actual == 0,
        }

    # ------------------------------------------------------------------ reversal & estimated -> billed correction (CR-40)
    def reverse_ledger_entry(
        self,
        tenant_id: str,
        reverses_entry_id: str,
        *,
        customer_micros: int | None = None,
        entry_kind: str = "adjustment",
        idempotency_key: str | None = None,
        price_table_version: str | None = None,
    ) -> UsageLedgerEntry:
        """Append a single reversal adjustment row in `usage_ledger` per `core.enforce_reversal` (CR-40)."""
        if entry_kind != "adjustment":
            raise LedgerReversalError("reversals must be adjustment entries")
        orig = next(
            (e for e in self._ledger if e.tenant_id == tenant_id and e.entry_id == reverses_entry_id),
            None,
        )
        if orig is None:
            raise LedgerReversalError(f"unknown ledger entry {reverses_entry_id}")
        expected_micros = -orig.customer_micros
        actual_micros = expected_micros if customer_micros is None else _require_signed_int(customer_micros, "customer_micros")
        if actual_micros != expected_micros:
            raise LedgerReversalError("reversal must negate the original amount")
        if any(e.tenant_id == tenant_id and e.reverses_entry_id == reverses_entry_id for e in self._ledger):
            raise LedgerReversalError("entry already reversed")

        return self._append_ledger_entry(
            tenant_id=tenant_id,
            project_id=orig.project_id,
            entry_kind="adjustment",
            customer_micros=actual_micros,
            provider_cost_micros=0,
            receipt_id=orig.receipt_id,
            reverses_entry_id=reverses_entry_id,
            idempotency_key=idempotency_key or f"reverse:{reverses_entry_id}",
            price_table_version=price_table_version or orig.price_table_version,
        )

    def reconcile_estimated_to_billed(
        self,
        billed_document: dict,
        *,
        price_table_version: str = "pt_v1",
    ) -> dict:
        """Reconcile a previously recorded `source='estimated'` receipt with a final `source='provider_billed'` receipt.

        Policy:
          1. Never mutates or deletes the original estimated receipt document or its ledger entry.
          2. Validates that the new document has `source == 'provider_billed'` and matches `(tenant_id, project_id, call_id, packet_id)`.
          3. If the estimated receipt had already been settled in `usage_ledger`, inserts an immutable single reversal
             (`entry_kind='adjustment'`, `reverses_entry_id=estimated_entry_id`, `customer_micros=+estimated_price`)
             followed by the final billed ledger entry (`model_usage` if >0 or zero-cost `adjustment` if 0).
          4. Updates `cost_reservations.actual_micros` and `overrun` to reflect the true provider-billed amount.
        """
        validated, _ = canonical_receipt(billed_document)
        if validated["source"] != "provider_billed":
            raise ReservationPolicyError("reconcile_estimated_to_billed requires source='provider_billed'")
        tenant_id = validated["tenant_id"]
        project_id = validated["project_id"]
        call_id = validated["call_id"]
        rkey = (tenant_id, project_id, call_id)
        active_id = self._active_receipt_by_call.get(rkey)
        if active_id is None:
            raise ReservationPolicyError(f"no existing receipt for call {call_id}")
        est_rec = self._receipts[active_id]
        if est_rec.source != "estimated":
            raise ReservationPolicyError(f"active receipt {active_id} already has source={est_rec.source}")
        if est_rec.packet_id != validated["packet_id"]:
            raise ReservationPolicyError("billed receipt packet_id does not match estimated receipt packet_id")
        if est_rec.receipt_id == validated["receipt_id"]:
            raise ReservationPolicyError("billed receipt must have a distinct receipt_id from the estimated receipt")

        billed_rec = self.record_receipt(
            billed_document,
            price_table_version=price_table_version,
            allow_supersede_estimated=True,
        )
        self._receipts[est_rec.receipt_id] = StoredReceiptRecord(
            **{**est_rec.__dict__, "superseded_by_receipt_id": billed_rec.receipt_id}
        )

        reversal_entry_id: str | None = None
        res = self._reservations[rkey]
        if est_rec.ledger_entry_id is not None:
            rev = self.reverse_ledger_entry(
                tenant_id=tenant_id,
                reverses_entry_id=est_rec.ledger_entry_id,
                idempotency_key=f"reverse:{est_rec.ledger_entry_id}",
                price_table_version=price_table_version,
            )
            reversal_entry_id = rev.entry_id

        # If reservation was still RESERVED, settle_receipt handles the transition; if already COMMITTED from estimated,
        # record the replacement ledger entry and update actual_micros / overrun.
        if res.status == "RESERVED":
            settled = self.settle_receipt(tenant_id, project_id, billed_rec.receipt_id)
            billed_entry_id = settled["ledger_entry_id"]
        else:
            actual = billed_rec.customer_price_micros
            overrun = actual > res.reserved_micros
            self._reservations[rkey] = CostReservationRecord(
                tenant_id=res.tenant_id,
                project_id=res.project_id,
                request_key=res.request_key,
                period_start=res.period_start,
                reserved_micros=res.reserved_micros,
                actual_micros=actual,
                status="COMMITTED",
                overrun=overrun,
                created_at=res.created_at,
            )
            if actual > 0:
                entry = self._append_ledger_entry(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    entry_kind="model_usage",
                    customer_micros=-actual,
                    provider_cost_micros=billed_rec.cost_micros,
                    receipt_id=billed_rec.receipt_id,
                    reverses_entry_id=None,
                    idempotency_key=f"settle-billed:{call_id}:{billed_rec.receipt_id}",
                    price_table_version=price_table_version,
                )
            else:
                entry = self._append_ledger_entry(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    entry_kind="adjustment",
                    customer_micros=0,
                    provider_cost_micros=billed_rec.cost_micros,
                    receipt_id=billed_rec.receipt_id,
                    reverses_entry_id=None,
                    idempotency_key=f"settle-billed:{call_id}:{billed_rec.receipt_id}",
                    price_table_version=price_table_version,
                )
            billed_entry_id = entry.entry_id
            self._receipts[billed_rec.receipt_id] = StoredReceiptRecord(
                **{**billed_rec.__dict__, "ledger_entry_id": billed_entry_id}
            )

        updated_res = self._reservations[rkey]
        return {
            "call_id": call_id,
            "superseded_estimated_receipt_id": est_rec.receipt_id,
            "billed_receipt_id": billed_rec.receipt_id,
            "reversal_entry_id": reversal_entry_id,
            "billed_ledger_entry_id": billed_entry_id,
            "estimated_customer_micros": est_rec.customer_price_micros,
            "billed_customer_micros": billed_rec.customer_price_micros,
            "net_delta_micros": billed_rec.customer_price_micros - est_rec.customer_price_micros,
            "overrun": updated_res.overrun,
        }

    # ------------------------------------------------------------------ KPI filtering (CR-13)
    def filter_kpi_eligible_receipts(self, tenant_id: str, project_id: str | None = None) -> list[StoredReceiptRecord]:
        """Return only active `source='provider_billed'` receipts settled in the ledger (`CR-13`).

        Receipts with `source='estimated'` or superseded receipts are strictly excluded from official KPIs.
        """
        out: list[StoredReceiptRecord] = []
        for rec in self._receipts.values():
            if rec.tenant_id != tenant_id:
                continue
            if project_id is not None and rec.project_id != project_id:
                continue
            if rec.source != "provider_billed":
                continue
            if rec.superseded_by_receipt_id is not None:
                continue
            if rec.ledger_entry_id is None:
                continue
            out.append(rec)
        return sorted(out, key=lambda r: r.receipt_id)

    def aggregate_verified_kpi(self, tenant_id: str, project_id: str | None = None) -> dict:
        eligible = self.filter_kpi_eligible_receipts(tenant_id, project_id)
        excluded_estimated = sum(
            1
            for r in self._receipts.values()
            if r.tenant_id == tenant_id
            and (project_id is None or r.project_id == project_id)
            and r.source == "estimated"
        )
        return {
            "eligible_receipt_count": len(eligible),
            "excluded_estimated_count": excluded_estimated,
            "total_cost_micros": sum(r.cost_micros for r in eligible),
            "total_customer_price_micros": sum(r.customer_price_micros for r in eligible),
            "total_input_tokens": sum(r.document["tokens"]["uncached_input"] for r in eligible),
            "total_cached_tokens": sum(r.document["tokens"]["cache_read"] for r in eligible),
            "total_output_tokens": sum(r.document["tokens"]["output"] for r in eligible),
        }

    # ------------------------------------------------------------------ internal ledger append
    def _append_ledger_entry(
        self,
        *,
        tenant_id: str,
        project_id: str | None,
        entry_kind: str,
        customer_micros: int,
        provider_cost_micros: int,
        receipt_id: str | None,
        reverses_entry_id: str | None,
        idempotency_key: str,
        price_table_version: str,
    ) -> UsageLedgerEntry:
        if entry_kind not in ALL_LEDGER_KINDS:
            raise LedgerConstraintError(f"invalid entry_kind: {entry_kind}")
        _require_signed_int(customer_micros, "customer_micros")
        _require_non_neg_int(provider_cost_micros, "provider_cost_micros")
        if entry_kind in POSITIVE_LEDGER_KINDS and customer_micros <= 0:
            raise LedgerConstraintError(f"{entry_kind} requires customer_micros > 0")
        if entry_kind in NEGATIVE_LEDGER_KINDS and customer_micros >= 0:
            raise LedgerConstraintError(f"{entry_kind} requires customer_micros < 0")

        for existing in self._ledger:
            if existing.tenant_id == tenant_id and existing.idempotency_key == idempotency_key:
                raise LedgerConstraintError(f"duplicate idempotency_key {idempotency_key}")

        entry = UsageLedgerEntry(
            tenant_id=tenant_id,
            entry_id=str(uuid.uuid4()),
            project_id=project_id,
            entry_kind=entry_kind,
            customer_micros=customer_micros,
            provider_cost_micros=provider_cost_micros,
            receipt_id=receipt_id,
            reverses_entry_id=reverses_entry_id,
            idempotency_key=idempotency_key,
            price_table_version=price_table_version,
            recorded_at=time.time(),
        )
        self._ledger.append(entry)
        return entry

    def get_reservation(self, tenant_id: str, project_id: str, request_key: str) -> CostReservationRecord:
        return self._reservations[(tenant_id, project_id, request_key)]

    def get_receipt(self, receipt_id: str) -> StoredReceiptRecord:
        return self._receipts[receipt_id]

    def ledger_entries(self, tenant_id: str) -> list[UsageLedgerEntry]:
        return [e for e in self._ledger if e.tenant_id == tenant_id]


class UnknownReservationReconciler:
    """Automated reconciliation worker for UNKNOWN reservations (`DEVELOPMENT_STATUS.md` line 87).

    Supports both:
      1. `reconcile_micros_batch`: reconciles `UNKNOWN_EXTERNAL_OUTCOME` calls in `ReconcilerLedger`
         against a provider receipt lookup oracle.
      2. `reconcile_in_memory_unknowns`: reconciles `UNKNOWN` reservations in `evoforge.ledger`
         (`services/api/evoforge/ledger.py`) against a provider lookup oracle.
    """

    def __init__(self, ledger_engine: ReconcilerLedger | None = None) -> None:
        self.ledger = ledger_engine or ReconcilerLedger()

    def reconcile_micros_batch(
        self,
        oracle: Callable[[str, str, str], ProviderLookupOutcome],
        *,
        price_table_version: str = "pt_v1",
    ) -> dict:
        """Sweep all `UNKNOWN_EXTERNAL_OUTCOME` intents in `self.ledger` and settle or release them."""
        settled: list[dict] = []
        released: list[str] = []
        still_unknown: list[str] = []

        unknown_calls: list[tuple[str, str, str]] = []
        for (tenant_id, project_id, request_key), res in sorted(self.ledger._reservations.items()):
            if res.status != "RESERVED":
                continue
            iid = self.ledger._intents_by_key.get((tenant_id, "provider.call", request_key))
            if iid is None:
                continue
            intent = self.ledger.get_intent(tenant_id, iid)
            if intent.status == "UNKNOWN_EXTERNAL_OUTCOME":
                unknown_calls.append((tenant_id, project_id, request_key))

        for tenant_id, project_id, request_key in unknown_calls:
            outcome = oracle(tenant_id, project_id, request_key)
            if outcome.status == "BILLED":
                if outcome.receipt_document is None:
                    raise ReservationPolicyError(f"BILLED outcome for {request_key} missing receipt_document")
                rec = self.ledger.record_receipt(
                    outcome.receipt_document,
                    price_table_version=price_table_version,
                )
                s = self.ledger.settle_receipt(tenant_id, project_id, rec.receipt_id)
                settled.append(s)
            elif outcome.status == "NOT_ACCEPTED":
                self.ledger.release_not_accepted(tenant_id, project_id, request_key)
                released.append(request_key)
            elif outcome.status == "STILL_UNKNOWN":
                still_unknown.append(request_key)
            else:
                raise ValueError(f"unsupported ProviderLookupOutcome.status: {outcome.status}")

        return {
            "scanned": len(unknown_calls),
            "settled": settled,
            "released": released,
            "still_unknown": still_unknown,
        }

    @staticmethod
    def reconcile_in_memory_unknowns(
        project: str,
        oracle: Callable[[str], ProviderLookupOutcome],
    ) -> dict:
        """Sweep all `UNKNOWN` reservations for `project` in `evoforge.ledger` and settle/refund them."""
        snap = mem_ledger.snapshot(project)
        unknown_ids: list[str] = list(snap["unknown_reservations"])
        settled: list[dict] = []
        refunded: list[str] = []
        still_unknown: list[str] = []

        for rid in unknown_ids:
            outcome = oracle(rid)
            if outcome.status == "BILLED":
                res = mem_ledger.reconcile(rid, outcome.billed_cents, outcome.provider_request_id)
                settled.append(res)
            elif outcome.status == "NOT_ACCEPTED":
                mem_ledger.reconcile(rid, None, None)
                refunded.append(rid)
            elif outcome.status == "STILL_UNKNOWN":
                still_unknown.append(rid)
            else:
                raise ValueError(f"unsupported ProviderLookupOutcome.status: {outcome.status}")

        return {
            "project": project,
            "scanned": len(unknown_ids),
            "settled": settled,
            "refunded": refunded,
            "still_unknown": still_unknown,
        }
