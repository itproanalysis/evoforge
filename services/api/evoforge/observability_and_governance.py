"""Observability, SLO vs Safety Invariants, Billing Invoice/Webhook Reconciliation, and Lifecycle Governance.

Implements EvoForge v4.2 specification pages 45–50 (`EvoForge_v4.2_45.md` .. `EvoForge_v4.2_50.md`) and
Acceptance Test Matrix items:
- Canonical OpenTelemetry context & workflow spans (`EvoForge_v4.2_47.md`)
- R47-2: Strict separation between Service SLO panel and Safety Invariant panel (0-tolerance safety invariants)
- R47-3 & R48-3: Daily provider invoice vs canonical receipt reconciliation and >1% drift alert + root-cause classification
- R47-4: v4.1 performance technique monitoring with sample sizes, auto-disable speculation on >=1 mismatch,
  reward-hacking canary quarantine, and verification Runner >=80% utilization upstream throttle recommendation
- R48-1 & R48-2: Payment PG webhook duplicate, out-of-order, and partial-refund reconciliation with 0 duplicate charges
- Incident response state machine (`Detect -> Triage -> Contain -> Recover -> Communicate -> RCA -> Prevent`)
  and independent operator kill-switch + supply-chain incident runbook
- CR-22: Objective version mutation marks task context packets `STALE`, blocks approval, and forbids revival
- CR-24: Codec feature-flag OFF falls back cleanly to `RAW` without breaking existing pipeline
- CR-69: S11 cache breakpoint placement validator (no breakpoint on L3, no tool_output/untrusted in cached prefix)
- CR-17 & R46-2: Crypto-shredding deletion cascade across blobs, DEKs, refs, packets, indexes, embeddings, and playbooks
- R49-1, R49-5 & R50-1: Milestone & GA Release Evidence Package builder and verifier (enforcing `muse-spark-1.3` and holdout >= 200)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any
import uuid


CANONICAL_CONTEXT_SPANS: frozenset[str] = frozenset(
    {
        "context.detect",
        "context.original_store",
        "context.compress",
        "context.assemble",
        "context.retrieve",
        "provider.cache_decision",
    }
)
CANONICAL_WORKFLOW_SPANS: frozenset[str] = frozenset(
    {
        "command.dispatch",
        "provider.call",
        "runner.exec",
        "ci.verify",
        "merge.authorize",
    }
)
ALL_CANONICAL_SPANS: frozenset[str] = CANONICAL_CONTEXT_SPANS | CANONICAL_WORKFLOW_SPANS

SAFETY_INVARIANT_KEYS: tuple[str, ...] = (
    "unauthorized_merge_or_deploy",
    "cross_tenant_exposure",
    "secret_leak",
    "budget_or_credit_overrun_execution",
    "inflight_work_loss",
    "unauthorized_platform_key_decrypt",
)

INCIDENT_PHASES: tuple[str, ...] = (
    "DETECT",
    "TRIAGE",
    "CONTAIN",
    "RECOVER",
    "COMMUNICATE",
    "RCA",
    "PREVENT",
)

SUPPLY_CHAIN_RUNBOOK_STEPS: tuple[str, ...] = (
    "isolate_dependency",
    "restrict_egress",
    "enumerate_affected_artifacts",
    "rotate_platform_keys",
    "rebuild_clean_images",
    "preserve_forensic_evidence",
    "notify_tenants",
)


class GovernanceError(ValueError):
    """Raised when an observability, billing, lifecycle, or release governance invariant fails."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TelemetrySpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    tenant_id: str
    project_id: str
    duration_ms: float
    attributes: dict[str, Any]


class CanonicalTelemetryTracer:
    """OpenTelemetry-aligned tracer enforcing canonical context and workflow span vocabulary (`EvoForge_v4.2_47.md`)."""

    def __init__(self) -> None:
        self._spans: list[TelemetrySpan] = []

    def record_span(
        self,
        *,
        trace_id: str,
        name: str,
        tenant_id: str,
        project_id: str,
        duration_ms: float,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> TelemetrySpan:
        if name not in ALL_CANONICAL_SPANS:
            raise GovernanceError("UNKNOWN_CANONICAL_SPAN", f"span {name!r} is not in canonical span catalog")
        span = TelemetrySpan(
            trace_id=trace_id,
            span_id=str(uuid.uuid4()),
            parent_span_id=parent_span_id,
            name=name,
            tenant_id=tenant_id,
            project_id=project_id,
            duration_ms=float(duration_ms),
            attributes=copy.deepcopy(attributes or {}),
        )
        self._spans.append(span)
        return span

    def spans_for_trace(self, trace_id: str) -> list[TelemetrySpan]:
        return [s for s in self._spans if s.trace_id == trace_id]


class SLOVsSafetyMonitor:
    """Separates Service SLO evaluation from Safety Invariant monitoring and v4.1 technique auto-guards (`R47-2`, `R47-4`)."""

    def __init__(self) -> None:
        self.safety_violations: dict[str, int] = {k: 0 for k in SAFETY_INVARIANT_KEYS}
        self.speculation_globally_enabled: bool = True
        self.speculation_mismatch_count: int = 0
        self.canary_quarantined_configs: set[tuple[str, str]] = set()
        self.incidents_triggered: list[dict[str, Any]] = []

    def record_safety_violation(self, invariant_key: str, *, details: str = "") -> dict[str, Any]:
        if invariant_key not in self.safety_violations:
            raise GovernanceError("UNKNOWN_SAFETY_INVARIANT", f"unknown safety invariant {invariant_key!r}")
        self.safety_violations[invariant_key] += 1
        inc = {
            "incident_id": str(uuid.uuid4()),
            "invariant": invariant_key,
            "count": self.safety_violations[invariant_key],
            "details": details,
            "phase": "DETECT",
        }
        self.incidents_triggered.append(inc)
        return inc

    def evaluate_dashboard_panels(
        self,
        *,
        valid_requests: int,
        successful_responses: int,
        command_ack_p95_ms: float,
        ui_commit_reflect_p95_ms: float,
        reconnect_converge_p95_ms: float,
        stop_all_apply_p95_ms: float,
    ) -> dict[str, Any]:
        """Return strictly separated `service_slo_panel` and `safety_invariant_panel` (`R47-2`)."""
        availability_pct = (successful_responses / max(valid_requests, 1)) * 100.0
        slo_checks = {
            "api_availability": {
                "value_pct": round(availability_pct, 4),
                "target_pct": 99.9,
                "met": availability_pct >= 99.9,
            },
            "command_ack_p95": {
                "value_ms": command_ack_p95_ms,
                "target_ms": 2000.0,
                "met": command_ack_p95_ms < 2000.0,
            },
            "ui_commit_reflect_p95": {
                "value_ms": ui_commit_reflect_p95_ms,
                "target_ms": 3000.0,
                "met": ui_commit_reflect_p95_ms < 3000.0,
            },
            "reconnect_converge_p95": {
                "value_ms": reconnect_converge_p95_ms,
                "target_ms": 10000.0,
                "met": reconnect_converge_p95_ms < 10000.0,
            },
            "stop_all_apply_p95": {
                "value_ms": stop_all_apply_p95_ms,
                "target_ms": 5000.0,
                "met": stop_all_apply_p95_ms < 5000.0,
            },
        }
        all_slo_met = all(item["met"] for item in slo_checks.values())
        total_safety_violations = sum(self.safety_violations.values())

        return {
            "panels_separated": True,
            "service_slo_panel": {
                "panel_id": "service_slo",
                "all_met": all_slo_met,
                "metrics": slo_checks,
            },
            "safety_invariant_panel": {
                "panel_id": "safety_invariants",
                "target_violations": 0,
                "total_violations": total_safety_violations,
                "healthy": total_safety_violations == 0,
                "invariants": copy.deepcopy(self.safety_violations),
                "active_incidents": len(self.incidents_triggered),
            },
        }

    def evaluate_performance_techniques(
        self,
        *,
        model: str,
        harness_version: str,
        composition_runs: int,
        composition_interferences: int,
        integrity_evals: int,
        integrity_flags: int,
        visible_pass_rate: float,
        heldout_pass_rate: float,
        speculation_trials: int,
        speculation_accepted: int,
        speculation_mismatches: int,
        samples_per_task_k: float,
        cascade_trials: int,
        cascade_escalations: int,
        verification_runner_utilization: float = 0.5,
        runner_utilization_increasing: bool = False,
    ) -> dict[str, Any]:
        """Monitor v4.1 performance techniques with sample counts and trigger automatic safety actions (`R47-4`)."""
        if speculation_mismatches >= 1:
            self.speculation_mismatch_count += speculation_mismatches
            self.speculation_globally_enabled = False

        visible_heldout_gap = max(0.0, visible_pass_rate - heldout_pass_rate)
        integrity_flag_rate = integrity_flags / max(integrity_evals, 1)
        reward_hacking_alert = visible_heldout_gap > 0.25 or integrity_flag_rate > 0.15
        if reward_hacking_alert:
            self.canary_quarantined_configs.add((model, harness_version))

        runner_recommendation = "NORMAL"
        if verification_runner_utilization >= 0.80 and runner_utilization_increasing:
            runner_recommendation = "RECOMMEND_UPSTREAM_THROTTLE_OR_SCALE"

        return {
            "technique_panels": {
                "composition": {
                    "n": composition_runs,
                    "interference_rate": composition_interferences / max(composition_runs, 1),
                },
                "integrity": {
                    "n": integrity_evals,
                    "integrity_flag_rate": integrity_flag_rate,
                    "visible_heldout_gap": round(visible_heldout_gap, 4),
                },
                "speculation": {
                    "n": speculation_trials,
                    "accept_ratio": speculation_accepted / max(speculation_trials, 1),
                    "mismatches": speculation_mismatches,
                    "globally_enabled": self.speculation_globally_enabled,
                },
                "sampling": {
                    "n": integrity_evals,
                    "samples_per_task_k": samples_per_task_k,
                },
                "cascade": {
                    "n": cascade_trials,
                    "escalation_rate": cascade_escalations / max(cascade_trials, 1),
                },
            },
            "speculation_globally_enabled": self.speculation_globally_enabled,
            "reward_hacking_alert": reward_hacking_alert,
            "canary_quarantined": (model, harness_version) in self.canary_quarantined_configs,
            "runner_capacity_action": runner_recommendation,
        }


class BillingInvoiceAndWebhookReconciler:
    """Daily provider invoice vs canonical receipt drift monitor (`R47-3`, `R48-3`) and PG webhook engine (`R48-1`)."""

    def __init__(self, *, drift_alert_threshold: float = 0.01):
        self.drift_alert_threshold = drift_alert_threshold
        self._processed_webhooks: dict[tuple[str, str], dict[str, Any]] = {}
        self._ledger_entries: list[dict[str, Any]] = []
        self._payment_totals_by_tx: dict[tuple[str, str], int] = {}
        self._refunded_totals_by_tx: dict[tuple[str, str], int] = {}
        self._pending_refunds_by_tx: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def reconcile_daily_provider_invoice(
        self,
        *,
        provider: str,
        billing_date: str,
        receipts: list[dict[str, Any]],
        invoice_lines: list[dict[str, Any]],
        expected_price_table_version: str = "pt_2026_10_v1",
    ) -> dict[str, Any]:
        """Compare provider invoice lines against `provider_billed` receipts (`R47-3`, `R48-3`)."""
        billed_receipts = {
            str(r["provider_request_id"]): r
            for r in receipts
            if r.get("provider") == provider and r.get("source") == "provider_billed" and r.get("provider_request_id")
        }
        invoice_by_req = {
            str(line["provider_request_id"]): line
            for line in invoice_lines
            if line.get("provider") == provider and line.get("provider_request_id")
        }

        receipt_total = sum(int(r.get("cost_micros", 0)) for r in billed_receipts.values())
        invoice_total = sum(int(line.get("billed_cost_micros", 0)) for line in invoice_by_req.values())
        denom = max(invoice_total, receipt_total, 1)
        drift_ratio = abs(invoice_total - receipt_total) / denom

        discrepancies: list[dict[str, Any]] = []
        all_req_ids = sorted(set(billed_receipts.keys()) | set(invoice_by_req.keys()))
        for req_id in all_req_ids:
            rcpt = billed_receipts.get(req_id)
            inv = invoice_by_req.get(req_id)
            if rcpt is None and inv is not None:
                discrepancies.append(
                    {
                        "provider_request_id": req_id,
                        "cause": "MISSING_RECEIPT",
                        "invoice_micros": int(inv.get("billed_cost_micros", 0)),
                        "receipt_micros": 0,
                    }
                )
            elif inv is None and rcpt is not None:
                discrepancies.append(
                    {
                        "provider_request_id": req_id,
                        "cause": "UNBILLED_RECEIPT",
                        "invoice_micros": 0,
                        "receipt_micros": int(rcpt.get("cost_micros", 0)),
                    }
                )
            elif rcpt is not None and inv is not None:
                r_cost = int(rcpt.get("cost_micros", 0))
                i_cost = int(inv.get("billed_cost_micros", 0))
                if r_cost != i_cost:
                    cause = (
                        "PRICE_TABLE_DRIFT"
                        if rcpt.get("price_table_version") != expected_price_table_version
                        else "AMOUNT_MISMATCH"
                    )
                    discrepancies.append(
                        {
                            "provider_request_id": req_id,
                            "cause": cause,
                            "invoice_micros": i_cost,
                            "receipt_micros": r_cost,
                        }
                    )

        return {
            "provider": provider,
            "billing_date": billing_date,
            "receipt_total_micros": receipt_total,
            "invoice_total_micros": invoice_total,
            "drift_ratio": round(drift_ratio, 6),
            "alert_triggered": drift_ratio > self.drift_alert_threshold,
            "discrepancies": discrepancies,
        }

    def ingest_payment_webhook(self, webhook: dict[str, Any]) -> dict[str, Any]:
        """Process PG webhooks with duplicate, out-of-order, and partial-refund safety (`R48-1`, `R48-2`)."""
        tenant_id = str(webhook["tenant_id"])
        webhook_id = str(webhook["webhook_id"])
        event_type = str(webhook["event_type"])
        tx_id = str(webhook["transaction_id"])
        amount_micros = int(webhook["amount_micros"])
        if amount_micros <= 0:
            raise GovernanceError("INVALID_WEBHOOK_AMOUNT", "webhook amount_micros must be > 0")

        wkey = (tenant_id, webhook_id)
        if wkey in self._processed_webhooks:
            return {"status": "DUPLICATE_IGNORED", "entry": self._processed_webhooks[wkey]}

        tx_key = (tenant_id, tx_id)

        if event_type == "payment.succeeded":
            entry = {
                "entry_id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "transaction_id": tx_id,
                "entry_kind": "credit_purchase",
                "customer_micros": amount_micros,
                "idempotency_key": f"pg:{tx_id}:purchase",
            }
            self._ledger_entries.append(entry)
            self._payment_totals_by_tx[tx_key] = amount_micros
            self._processed_webhooks[wkey] = entry

            # Drain any out-of-order refund webhooks that arrived before payment.succeeded
            pending = self._pending_refunds_by_tx.pop(tx_key, [])
            for p_wh in pending:
                self._apply_refund_webhook(p_wh)

            return {"status": "APPLIED", "entry": entry}

        if event_type in {"payment.refunded", "payment.partial_refunded"}:
            if tx_key not in self._payment_totals_by_tx:
                # Out-of-order arrival: buffer until corresponding payment.succeeded arrives
                self._pending_refunds_by_tx.setdefault(tx_key, []).append(copy.deepcopy(webhook))
                return {"status": "BUFFERED_OUT_OF_ORDER", "transaction_id": tx_id}
            entry = self._apply_refund_webhook(webhook)
            return {"status": "APPLIED", "entry": entry}

        raise GovernanceError("UNSUPPORTED_WEBHOOK_EVENT", f"unsupported payment event {event_type!r}")

    def _apply_refund_webhook(self, webhook: dict[str, Any]) -> dict[str, Any]:
        tenant_id = str(webhook["tenant_id"])
        webhook_id = str(webhook["webhook_id"])
        tx_id = str(webhook["transaction_id"])
        amount_micros = int(webhook["amount_micros"])
        wkey = (tenant_id, webhook_id)
        if wkey in self._processed_webhooks:
            return self._processed_webhooks[wkey]

        tx_key = (tenant_id, tx_id)
        paid = self._payment_totals_by_tx.get(tx_key, 0)
        already_refunded = self._refunded_totals_by_tx.get(tx_key, 0)
        if already_refunded + amount_micros > paid:
            raise GovernanceError(
                "REFUND_EXCEEDS_PAYMENT",
                f"refund {already_refunded + amount_micros} exceeds original payment {paid} for tx {tx_id}",
            )
        self._refunded_totals_by_tx[tx_key] = already_refunded + amount_micros
        entry = {
            "entry_id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "transaction_id": tx_id,
            "entry_kind": "refund",
            "customer_micros": -amount_micros,
            "idempotency_key": f"pg:{tx_id}:refund:{webhook_id}",
        }
        self._ledger_entries.append(entry)
        self._processed_webhooks[wkey] = entry
        return entry

    def tenant_credit_balance(self, tenant_id: str) -> int:
        return sum(e["customer_micros"] for e in self._ledger_entries if e["tenant_id"] == tenant_id)


class IncidentAndLifecycleGovernance:
    """Incident response state machine (`EvoForge_v4.2_47.md`), Context lifecycle guards (`CR-17`, `CR-22`, `CR-24`, `CR-69`),
    and Milestone / GA Release Evidence Package verifier (`R49-1`, `R49-5`, `R50-1`).
    """

    def __init__(self) -> None:
        self._incidents: dict[str, dict[str, Any]] = {}
        self.operator_kill_switch: dict[str, bool] = {
            "merge_blocked": False,
            "deploy_blocked": False,
            "provider_adapters_blocked": False,
        }
        # (tenant_id, task_id) -> {"objective_version": int, "packets": dict[packet_id, status]}
        self._task_packets: dict[tuple[str, str], dict[str, Any]] = {}
        # (tenant_id, blob_id) -> blob metadata for crypto-shredding cascade (CR-17, R46-2)
        self._blobs: dict[tuple[str, str], dict[str, Any]] = {}

    # ------------------------------------------------------------------ Incident State Machine (Page 47)
    def open_incident(self, *, incident_id: str, kind: str, summary: str) -> dict[str, Any]:
        inc = {
            "incident_id": incident_id,
            "kind": kind,
            "summary": summary,
            "phase": "DETECT",
            "history": ["DETECT"],
            "supply_chain_steps_completed": [],
        }
        self._incidents[incident_id] = inc
        return copy.deepcopy(inc)

    def advance_incident_phase(
        self,
        incident_id: str,
        target_phase: str,
        *,
        operator_override: bool = True,
    ) -> dict[str, Any]:
        if incident_id not in self._incidents:
            raise GovernanceError("UNKNOWN_INCIDENT", f"unknown incident {incident_id}")
        if target_phase not in INCIDENT_PHASES:
            raise GovernanceError("INVALID_INCIDENT_PHASE", f"invalid phase {target_phase!r}")
        inc = self._incidents[incident_id]
        cur_idx = INCIDENT_PHASES.index(inc["phase"])
        tgt_idx = INCIDENT_PHASES.index(target_phase)
        if tgt_idx != cur_idx + 1:
            raise GovernanceError(
                "ILLEGAL_INCIDENT_TRANSITION",
                f"incident must follow ordered phases {INCIDENT_PHASES}; cannot jump {inc['phase']} -> {target_phase}",
            )
        inc["phase"] = target_phase
        inc["history"].append(target_phase)

        if target_phase == "CONTAIN" and operator_override:
            self.operator_kill_switch["merge_blocked"] = True
            self.operator_kill_switch["deploy_blocked"] = True
            self.operator_kill_switch["provider_adapters_blocked"] = True
        elif target_phase == "RECOVER" and operator_override:
            self.operator_kill_switch["merge_blocked"] = False
            self.operator_kill_switch["deploy_blocked"] = False
            self.operator_kill_switch["provider_adapters_blocked"] = False

        return copy.deepcopy(inc)

    def execute_supply_chain_runbook(self, incident_id: str) -> dict[str, Any]:
        if incident_id not in self._incidents:
            raise GovernanceError("UNKNOWN_INCIDENT", f"unknown incident {incident_id}")
        inc = self._incidents[incident_id]
        inc["supply_chain_steps_completed"] = list(SUPPLY_CHAIN_RUNBOOK_STEPS)
        self.operator_kill_switch["merge_blocked"] = True
        self.operator_kill_switch["deploy_blocked"] = True
        self.operator_kill_switch["provider_adapters_blocked"] = True
        return copy.deepcopy(inc)

    # ------------------------------------------------------------------ CR-22: Objective mutation marks packets STALE
    def register_task_packet(
        self,
        *,
        tenant_id: str,
        task_id: str,
        packet_id: str,
        objective_version: int,
    ) -> dict[str, Any]:
        tkey = (tenant_id, task_id)
        entry = self._task_packets.setdefault(
            tkey, {"objective_version": objective_version, "packets": {}}
        )
        entry["packets"][packet_id] = "ACTIVE"
        return {"packet_id": packet_id, "status": "ACTIVE", "objective_version": entry["objective_version"]}

    def update_task_objective_version(
        self,
        *,
        tenant_id: str,
        task_id: str,
        new_objective_version: int,
    ) -> dict[str, Any]:
        """Mark all existing task packets `STALE` when `objective_version` changes (`CR-22`)."""
        tkey = (tenant_id, task_id)
        entry = self._task_packets.setdefault(
            tkey, {"objective_version": new_objective_version, "packets": {}}
        )
        if new_objective_version <= entry["objective_version"]:
            raise GovernanceError("INVALID_OBJECTIVE_VERSION", "new_objective_version must strictly increase")
        entry["objective_version"] = new_objective_version
        staled = []
        for pid, status in list(entry["packets"].items()):
            if status == "ACTIVE":
                entry["packets"][pid] = "STALE"
                staled.append(pid)
        return {"task_id": task_id, "new_objective_version": new_objective_version, "staled_packets": staled}

    def revive_packet(self, *, tenant_id: str, task_id: str, packet_id: str) -> None:
        tkey = (tenant_id, task_id)
        status = self._task_packets.get(tkey, {}).get("packets", {}).get(packet_id)
        if status in {"STALE", "REVOKED"}:
            raise GovernanceError(
                "STALE_PACKET_REVIVAL_FORBIDDEN",
                f"packet {packet_id} is {status} and cannot be revived (CR-22)",
            )

    def assert_packet_approvable(self, *, tenant_id: str, task_id: str, packet_id: str) -> None:
        tkey = (tenant_id, task_id)
        status = self._task_packets.get(tkey, {}).get("packets", {}).get(packet_id)
        if status != "ACTIVE":
            raise GovernanceError(
                "PACKET_NOT_ACTIVE",
                f"approval blocked: packet {packet_id} has status {status!r} (CR-22)",
            )

    # ------------------------------------------------------------------ CR-24 & CR-69: Codec Feature Flag & S11 Cache Placement
    @staticmethod
    def encode_with_feature_flag(
        *,
        source_kind: str,
        raw_content: str,
        codec_feature_flag_enabled: bool,
        encoder_fn: Any = None,
    ) -> dict[str, Any]:
        """When codec feature flag is OFF (`CR-24`), cleanly return `RAW(POLICY_RAW_ONLY)` on existing path."""
        if not codec_feature_flag_enabled or encoder_fn is None:
            return {
                "representation": "RAW",
                "raw_fallback_reason": "POLICY_RAW_ONLY",
                "source_kind": source_kind,
                "content": raw_content,
                "feature_flag_enabled": False,
            }
        return encoder_fn(raw_content)

    @staticmethod
    def validate_s11_cache_placement(packet: dict[str, Any]) -> None:
        """Enforce S11 cache layout (`CR-69`): breakpoints only in L0–L2, no tool_output/untrusted inside cached prefix."""
        cache_plan = packet.get("cache_plan", {})
        breakpoints = cache_plan.get("breakpoints", [])
        for bp in breakpoints:
            layer = bp.get("layer") if isinstance(bp, dict) else str(bp)
            if layer == "L3" or "L3" in str(layer):
                raise GovernanceError(
                    "S11_BREAKPOINT_ON_L3",
                    "cache breakpoint on L3 (task delta) violates S11 (CR-69)",
                )

        for item in packet.get("items", []):
            layer = item.get("layer", "")
            in_cached_prefix = layer in {"L0", "L1", "L2"} or bool(item.get("in_cached_prefix", False))
            if in_cached_prefix:
                if item.get("trust_level") == "untrusted" or item.get("trust") == "untrusted":
                    raise GovernanceError(
                        "S11_UNTRUSTED_IN_PREFIX",
                        "untrusted item inside cached prefix L0–L2 violates S2/S11 (CR-11, CR-69)",
                    )
                if item.get("item_kind") == "tool_output" or item.get("source_kind", "").startswith("tool."):
                    raise GovernanceError(
                        "S11_TOOL_OUTPUT_IN_PREFIX",
                        "dynamic tool output inside cached prefix L0–L2 violates S11 (CR-69)",
                    )

    # ------------------------------------------------------------------ CR-17 & R46-2: Crypto-shredding Deletion Cascade
    def register_blob_with_derivations(
        self,
        *,
        tenant_id: str,
        blob_id: str,
        dek_id: str,
        evidence_refs: list[str],
        dependent_packet_ids: list[str],
        search_index_ids: list[str],
        embedding_ids: list[str],
        playbook_lesson_ids: list[str],
        legal_hold: bool = False,
        backup_expiry_iso: str = "2026-11-27T00:00:00Z",
    ) -> dict[str, Any]:
        rec = {
            "tenant_id": tenant_id,
            "blob_id": blob_id,
            "status": "ACTIVE",
            "dek_id": dek_id,
            "dek_destroyed": False,
            "legal_hold": legal_hold,
            "refs": {r: "ACTIVE" for r in evidence_refs},
            "packets": {p: "ACTIVE" for p in dependent_packet_ids},
            "search_index": list(search_index_ids),
            "embeddings": list(embedding_ids),
            "playbook_lessons": list(playbook_lesson_ids),
            "backup_expiry_iso": backup_expiry_iso,
        }
        self._blobs[(tenant_id, blob_id)] = rec
        return copy.deepcopy(rec)

    def shred_blob_and_cascade(self, *, tenant_id: str, blob_id: str) -> dict[str, Any]:
        """Execute `ctx.shred_blob` + derived index/embedding/playbook purge (`CR-17`, `R46-2`)."""
        bkey = (tenant_id, blob_id)
        if bkey not in self._blobs:
            raise GovernanceError("BLOB_NOT_FOUND", f"unknown blob {blob_id}")
        rec = self._blobs[bkey]
        if rec["legal_hold"]:
            raise GovernanceError("LEGAL_HOLD_ACTIVE", f"blob {blob_id} is under legal hold; shred blocked (CR-17)")

        rec["status"] = "SHREDDED"
        rec["dek_id"] = None
        rec["dek_destroyed"] = True
        for r in list(rec["refs"].keys()):
            rec["refs"][r] = "REVOKED"
        for p in list(rec["packets"].keys()):
            rec["packets"][p] = "REVOKED"
        purged_counts = {
            "search_index": len(rec["search_index"]),
            "embeddings": len(rec["embeddings"]),
            "playbook_lessons": len(rec["playbook_lessons"]),
        }
        rec["search_index"].clear()
        rec["embeddings"].clear()
        rec["playbook_lessons"].clear()

        return {
            "tenant_id": tenant_id,
            "blob_id": blob_id,
            "status": rec["status"],
            "dek_destroyed": rec["dek_destroyed"],
            "revoked_refs": list(rec["refs"].keys()),
            "revoked_packets": list(rec["packets"].keys()),
            "purged_counts": purged_counts,
            "derived_remaining_count": (
                len(rec["search_index"]) + len(rec["embeddings"]) + len(rec["playbook_lessons"])
            ),
            "backup_expiration_schedule": {
                "immediate_purge_completed": True,
                "encrypted_backup_unreadable_via_dek_shred": True,
                "backup_retention_expires_at": rec["backup_expiry_iso"],
            },
        }

    # ------------------------------------------------------------------ R49-1, R49-5, R50-1: Release Evidence Package
    @staticmethod
    def build_and_verify_release_package(
        *,
        milestone: str,
        commit_sha: str,
        image_digest: str,
        harness_version_manifest: dict[str, Any],
        default_model: str,
        eval_set_sha: str,
        policy_sha: str,
        oracle_human_holdout_count: int,
        sandbox_hygiene_pass_rate: float,
        design_targets: dict[str, Any],
        measured_values: dict[str, Any],
        checklist_evidence_links: dict[str, str],
    ) -> dict[str, Any]:
        """Validate Milestone / GA Exit Evidence Package (`R49-1`, `R49-5`, `R50-1`)."""
        if default_model != "muse-spark-1.3":
            raise GovernanceError(
                "MODEL_DEFAULT_VIOLATION",
                f"EvoForge main model must remain 'muse-spark-1.3', got {default_model!r}",
            )
        if not commit_sha or not image_digest.startswith("sha256:") or not eval_set_sha or not policy_sha:
            raise GovernanceError("INCOMPLETE_ARTIFACT_HASHES", "commit, image, eval_set, and policy hashes are required")

        required_variants = {"T", "C", "S", "M", "W"}
        variants = set((harness_version_manifest.get("variants") or {}).keys())
        if variants != required_variants:
            raise GovernanceError(
                "INVALID_HARNESS_MANIFEST",
                f"HarnessVersionManifest must bind all 5 modules {sorted(required_variants)}",
            )

        if oracle_human_holdout_count < 200:
            raise GovernanceError(
                "ORACLE_HOLDOUT_UNDER_200",
                f"M0/GA exit requires >= 200 human-labeled oracle holdout items, got {oracle_human_holdout_count} (R49-5, D-054)",
            )
        if sandbox_hygiene_pass_rate < 1.0:
            raise GovernanceError(
                "SANDBOX_HYGIENE_INCOMPLETE",
                f"sandbox hygiene audit pass rate must be 1.0 (100%), got {sandbox_hygiene_pass_rate} (R49-5)",
            )
        if not design_targets or not measured_values:
            raise GovernanceError(
                "DESIGN_VS_MEASURED_MISSING",
                "release package must explicitly separate design_targets and measured_values (R50-1)",
            )
        if not checklist_evidence_links or any(not str(v).strip() for v in checklist_evidence_links.values()):
            raise GovernanceError("MISSING_CHECKLIST_EVIDENCE", "every checklist item requires a non-empty evidence link")

        manifest_bytes = json.dumps(
            {
                "milestone": milestone,
                "commit_sha": commit_sha,
                "image_digest": image_digest,
                "harness_version_manifest": harness_version_manifest,
                "default_model": default_model,
                "eval_set_sha": eval_set_sha,
                "policy_sha": policy_sha,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        return {
            "milestone": milestone,
            "package_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "commit_sha": commit_sha,
            "image_digest": image_digest,
            "default_model": default_model,
            "oracle_human_holdout_count": oracle_human_holdout_count,
            "sandbox_hygiene_pass_rate": sandbox_hygiene_pass_rate,
            "design_targets": copy.deepcopy(design_targets),
            "measured_values": copy.deepcopy(measured_values),
            "checklist_evidence_links": copy.deepcopy(checklist_evidence_links),
            "verified": True,
        }
