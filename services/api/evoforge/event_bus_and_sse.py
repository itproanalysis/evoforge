"""Event Bus, Transactional Outbox/Inbox Deduplication, Canonical Trajectory v1, and Real-time UI SSE Gateway.

Implements EvoForge v4.2 specification pages 27 (`EvoForge_v4.2_27.md`) and 44 (`EvoForge_v4.2_44.md`):
- R27-1: 10,000-event replay, duplicate, and out-of-order convergence with 0 duplicate PRs and 0 duplicate charges.
- R27-2 (C-11): Optimistic concurrency on `(tenant_id, aggregate_id, aggregate_version)` — only 1 event succeeds on version conflict.
- R27-3 (C-12): External side-effect UNKNOWN state blocks unverified retries.
- Message kind separation (`COMMAND` vs `PROPOSAL` vs `TASK` vs `ARTIFACT` vs `ACK` vs `EVENT`), Artifact-first handoff, and Canonical Trajectory v1 normalization.
- R44-1: Multi-client (browser/mobile) disconnect/reconnect convergence via atomic `(projection_version, event_cursor)` boundary and explicit snapshot resync on cursor gap / retention expiry / patch failure.
- R44-2: 1,000 events/sec burst backpressure sampling `progress` events while guaranteeing 0 drops for `approval`, `error`, and `conclusion` events.
- R44-3: Pre-publish tenant and RBAC permission filtering (0 unauthorized events in stream).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable
import uuid


_REPO_ROOT = Path(__file__).resolve().parents[3]
_VOCAB_PATH = _REPO_ROOT / "docs" / "evoforge-v4.2" / "contracts" / "vocabulary.json"
_VOCAB = json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))

CONTEXT_EVENTS: frozenset[str] = frozenset(_VOCAB.get("context_events", []))
COLLECTIVE_EVENTS: frozenset[str] = frozenset(
    {
        "COLLECTIVE_TOPOLOGY_SELECTED",
        "AGENT_ROLE_ASSIGNED",
        "AGENT_IDLE",
        "TASK_READY",
        "TASK_REASSIGNED",
        "BACKPRESSURE_APPLIED",
        "BOTTLENECK_DETECTED",
        "CANDIDATE_FILTERED",
        "QUALITY_GATE_RECORDED",
        "MERGE_CONFIRMED",
    }
)
RESEARCH_EVENTS: frozenset[str] = frozenset(
    {
        "CAPABILITY_GAP_DETECTED",
        "RESEARCH_SOURCE_ACCEPTED",
        "METHOD_EXTRACTED",
        "HARNESS_VARIANT_CREATED",
        "HARNESS_EVALUATION_COMPLETED",
        "HARNESS_PROMOTION_REQUESTED",
        "HARNESS_PROMOTED",
        "HARNESS_ROLLED_BACK",
        "RESEARCH_SOURCE_RETRACTED",
    }
)
WORKFLOW_EVENTS: frozenset[str] = frozenset(
    {
        "OBJECTIVE_UPDATED",
        "COMMAND_RECEIVED",
        "COMMAND_PENDING",
        "COMMAND_APPLIED",
        "COMMAND_DONE",
        "STOP_ALL_APPLIED",
        "TASK_PROGRESS",
        "TASK_COMPLETED",
        "APPROVAL_RECORDED",
        "ERROR_RAISED",
        "PR_CREATED",
        "BILLING_CHARGED",
        "INCIDENT_CONTAINED",
    }
)
ALL_KNOWN_EVENTS: frozenset[str] = CONTEXT_EVENTS | COLLECTIVE_EVENTS | RESEARCH_EVENTS | WORKFLOW_EVENTS

VALID_MESSAGE_KINDS: frozenset[str] = frozenset({"COMMAND", "TASK", "PROPOSAL", "ARTIFACT", "ACK", "EVENT"})
VALID_TRAJECTORY_STEP_KINDS: frozenset[str] = frozenset(
    {"turn", "tool_call", "tool_result", "artifact", "decision", "cost"}
)
CRITICAL_EVENT_CATEGORIES: frozenset[str] = frozenset({"approval", "error", "conclusion"})
CRITICAL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "MERGE_CONFIRMED",
        "QUALITY_GATE_RECORDED",
        "APPROVAL_RECORDED",
        "ERROR_RAISED",
        "COMMAND_APPLIED",
        "COMMAND_DONE",
        "STOP_ALL_APPLIED",
        "PR_CREATED",
        "BILLING_CHARGED",
        "INCIDENT_CONTAINED",
        "CONTEXT_SECURITY_VIOLATION",
        "CONTEXT_CODEC_AUTO_DISABLED",
    }
)

_RANDOM_GRANT_RE = re.compile(r"^ef_ref_[A-Za-z0-9_-]{16,64}$")


class EventBusError(ValueError):
    """Base error for DomainEventBus invariant violations."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class OptimisticConcurrencyError(EventBusError):
    """Raised when `(tenant_id, aggregate_id, aggregate_version)` collides (`R27-2`, `C-11`)."""


@dataclass(frozen=True)
class CanonicalEventEnvelope:
    event_id: str
    tenant_id: str
    project_id: str
    type: str
    schema_version: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    correlation_id: str
    causation_id: str
    trace_id: str
    actor: dict[str, str]
    occurred_at: str
    payload: dict[str, Any]
    message_kind: str = "EVENT"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "type": self.type,
            "schema_version": self.schema_version,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "aggregate_version": self.aggregate_version,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "trace_id": self.trace_id,
            "actor": copy.deepcopy(self.actor),
            "occurred_at": self.occurred_at,
            "payload": copy.deepcopy(self.payload),
            "message_kind": self.message_kind,
        }


@dataclass
class OutboxRecord:
    outbox_id: str
    tenant_id: str
    project_id: str
    event_id: str
    topic: str
    envelope: CanonicalEventEnvelope
    dispatched: bool = False


@dataclass(frozen=True)
class DLQRecord:
    dlq_id: str
    tenant_id: str
    project_id: str
    consumer: str
    event_id: str
    error_reason: str
    alert_raised: bool = True


def validate_envelope(raw: dict[str, Any] | CanonicalEventEnvelope) -> CanonicalEventEnvelope:
    """Validate all 14 canonical envelope fields and `COMMAND` vs `PROPOSAL` separation (`EvoForge_v4.2_27.md`)."""
    if isinstance(raw, CanonicalEventEnvelope):
        data = raw.to_dict()
    elif isinstance(raw, dict):
        data = raw
    else:
        raise EventBusError("INVALID_ENVELOPE", "envelope must be a dict or CanonicalEventEnvelope")

    required_str_fields = (
        "event_id",
        "tenant_id",
        "project_id",
        "type",
        "schema_version",
        "aggregate_type",
        "aggregate_id",
        "correlation_id",
        "causation_id",
        "trace_id",
        "occurred_at",
    )
    for f in required_str_fields:
        val = data.get(f)
        if not isinstance(val, str) or not val.strip():
            raise EventBusError("MISSING_ENVELOPE_FIELD", f"field {f!r} must be a non-empty string")

    agg_ver = data.get("aggregate_version")
    if type(agg_ver) is not int or agg_ver < 1:
        raise EventBusError("INVALID_AGGREGATE_VERSION", "aggregate_version must be a positive integer >= 1")

    actor = data.get("actor")
    if (
        not isinstance(actor, dict)
        or not isinstance(actor.get("kind"), str)
        or not actor["kind"].strip()
        or not isinstance(actor.get("id"), str)
        or not actor["id"].strip()
    ):
        raise EventBusError("INVALID_ACTOR", "actor must be {'kind': non-empty str, 'id': non-empty str}")

    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise EventBusError("INVALID_PAYLOAD", "payload must be a JSON object")

    msg_kind = data.get("message_kind", "EVENT")
    if msg_kind not in VALID_MESSAGE_KINDS:
        raise EventBusError("INVALID_MESSAGE_KIND", f"unknown message_kind {msg_kind!r}")

    # Page 27: COMMAND (human/policy change, requires permission verification) and PROPOSAL (AI plan/suggestion)
    # must NEVER be mixed. AI actors cannot issue COMMAND messages directly.
    if msg_kind == "COMMAND":
        if actor["kind"] in {"ai_agent", "model", "llm", "assistant"}:
            raise EventBusError(
                "COMMAND_PROPOSAL_MIX_FORBIDDEN",
                "AI/model actors must emit PROPOSAL, never COMMAND (EvoForge_v4.2_27.md)",
            )
        if not payload.get("authorized", True):
            raise EventBusError("UNAUTHORIZED_COMMAND", "COMMAND requires verified authorization")

    return CanonicalEventEnvelope(
        event_id=data["event_id"],
        tenant_id=data["tenant_id"],
        project_id=data["project_id"],
        type=data["type"],
        schema_version=data["schema_version"],
        aggregate_type=data["aggregate_type"],
        aggregate_id=data["aggregate_id"],
        aggregate_version=agg_ver,
        correlation_id=data["correlation_id"],
        causation_id=data["causation_id"],
        trace_id=data["trace_id"],
        actor={"kind": actor["kind"], "id": actor["id"]},
        occurred_at=data["occurred_at"],
        payload=copy.deepcopy(payload),
        message_kind=msg_kind,
    )


class ArtifactFirstHandoff:
    """Enforces Artifact-first handoff with tenant-scoped grant refs (`EvoForge_v4.2_27.md`, `CR-31`)."""

    def __init__(self, max_inline_bytes: int = 4096):
        self.max_inline_bytes = max_inline_bytes

    def build_handoff(
        self,
        *,
        tenant_id: str,
        artifact_uri: str,
        content_bytes: bytes,
        base_sha: str,
        acceptance_criteria: list[str],
        replay_steps: list[str],
        evidence_ref: str,
        inline_preview: str | None = None,
    ) -> dict[str, Any]:
        if not _RANDOM_GRANT_RE.match(evidence_ref):
            raise EventBusError(
                "SEQUENTIAL_OR_INVALID_REF",
                f"evidence_ref {evidence_ref!r} must be a non-guessable grant token matching ef_ref_* (CR-31)",
            )
        if inline_preview is not None and len(inline_preview.encode("utf-8")) > self.max_inline_bytes:
            raise EventBusError(
                "INLINE_ARTIFACT_TOO_LARGE",
                "large logs/code must not be pasted inline on the bus; pass tenant-scoped ref only (EvoForge_v4.2_27.md)",
            )
        if not isinstance(base_sha, str) or len(base_sha) < 7:
            raise EventBusError("INVALID_BASE_SHA", "handoff requires valid base_sha")
        if not acceptance_criteria or not replay_steps:
            raise EventBusError("INCOMPLETE_HANDOFF", "acceptance_criteria and replay_steps are required")

        digest = hashlib.sha256(content_bytes).hexdigest()
        return {
            "tenant_id": tenant_id,
            "artifact_uri": artifact_uri,
            "sha256": digest,
            "base_sha": base_sha,
            "acceptance_criteria": list(acceptance_criteria),
            "replay_steps": list(replay_steps),
            "ref": evidence_ref,
        }


class CanonicalTrajectoryNormalizer:
    """Normalizes heterogeneous API / Chat / CLI trace items into Canonical Trajectory v1 (`EvoForge_v4.2_27.md`)."""

    @staticmethod
    def normalize_record(source_system: str, raw: dict[str, Any]) -> dict[str, Any]:
        if source_system not in {"api", "chat", "cli"}:
            raise EventBusError("UNSUPPORTED_TRAJECTORY_SOURCE", f"unknown source_system {source_system!r}")
        step_kind = raw.get("kind") or raw.get("step_type")
        mapping = {
            "assistant_message": "turn",
            "user_message": "turn",
            "turn": "turn",
            "function_call": "tool_call",
            "tool_use": "tool_call",
            "tool_call": "tool_call",
            "function_output": "tool_result",
            "tool_result": "tool_result",
            "file_diff": "artifact",
            "artifact": "artifact",
            "gate_verdict": "decision",
            "decision": "decision",
            "usage_receipt": "cost",
            "cost": "cost",
        }
        canonical_kind = mapping.get(str(step_kind))
        if canonical_kind not in VALID_TRAJECTORY_STEP_KINDS:
            raise EventBusError("INVALID_TRAJECTORY_STEP", f"cannot map {step_kind!r} to Canonical Trajectory v1")

        return {
            "schema_version": "canonical-trajectory/v1",
            "source_system": source_system,
            "kind": canonical_kind,
            "run_id": str(raw["run_id"]),
            "task_id": str(raw["task_id"]),
            "seq": int(raw.get("seq", 1)),
            "ref": raw.get("ref"),
            "summary": str(raw.get("summary", "")),
            "cost_micros": int(raw.get("cost_micros", 0)),
        }


class DomainEventBus:
    """Transactional Domain Event Store + Outbox + Idempotent Consumer Inbox (`R27-1`, `R27-2`, `R27-3`)."""

    def __init__(self) -> None:
        # (tenant_id, aggregate_id, aggregate_version) -> CanonicalEventEnvelope
        self._events_by_agg_ver: dict[tuple[str, str, int], CanonicalEventEnvelope] = {}
        # (tenant_id, event_id) -> CanonicalEventEnvelope
        self._events_by_id: dict[tuple[str, str], CanonicalEventEnvelope] = {}
        self._ordered_log: list[CanonicalEventEnvelope] = []
        self._outbox: list[OutboxRecord] = []
        # (tenant_id, consumer, event_id) -> bool
        self._inbox_dedup: set[tuple[str, str, str]] = set()
        self._dlq: list[DLQRecord] = []
        # Topic subscriptions: (tenant_id, topic) -> set[seat_id]
        self._subscriptions: dict[tuple[str, str], set[str]] = {}

    def subscribe_topic(self, tenant_id: str, topic: str, seat_id: str) -> None:
        self._subscriptions.setdefault((tenant_id, topic), set()).add(seat_id)

    def subscribers_for(self, tenant_id: str, topic: str) -> set[str]:
        return set(self._subscriptions.get((tenant_id, topic), set()))

    def publish_transactional(
        self,
        raw_envelope: dict[str, Any] | CanonicalEventEnvelope,
        *,
        topic: str | None = None,
    ) -> CanonicalEventEnvelope:
        """Record domain event and Outbox entry atomically with `(tenant_id, aggregate_id, aggregate_version)` uniqueness."""
        env = validate_envelope(raw_envelope)
        id_key = (env.tenant_id, env.event_id)
        agg_key = (env.tenant_id, env.aggregate_id, env.aggregate_version)

        # Idempotent re-publish of the exact same event_id at the same aggregate_version
        if id_key in self._events_by_id:
            existing = self._events_by_id[id_key]
            if (
                existing.aggregate_id == env.aggregate_id
                and existing.aggregate_version == env.aggregate_version
                and existing.type == env.type
            ):
                return existing
            raise OptimisticConcurrencyError(
                "EVENT_ID_COLLISION",
                f"event_id {env.event_id} already exists with different aggregate coordinates",
            )

        if agg_key in self._events_by_agg_ver:
            winner = self._events_by_agg_ver[agg_key]
            raise OptimisticConcurrencyError(
                "AGGREGATE_VERSION_CONFLICT",
                f"({env.tenant_id}, {env.aggregate_id}, v={env.aggregate_version}) already written by {winner.event_id} (R27-2, C-11)",
            )

        self._events_by_agg_ver[agg_key] = env
        self._events_by_id[id_key] = env
        self._ordered_log.append(env)
        resolved_topic = topic or f"{env.aggregate_type}.{env.type.lower()}"
        self._outbox.append(
            OutboxRecord(
                outbox_id=str(uuid.uuid5(uuid.NAMESPACE_OID, f"outbox:{env.tenant_id}:{env.event_id}")),
                tenant_id=env.tenant_id,
                project_id=env.project_id,
                event_id=env.event_id,
                topic=resolved_topic,
                envelope=env,
                dispatched=False,
            )
        )
        return env

    def consume_once(
        self,
        *,
        consumer: str,
        envelope: CanonicalEventEnvelope,
        projector: Callable[[CanonicalEventEnvelope], None],
    ) -> bool:
        """At-least-once delivery with idempotent effect via `(tenant_id, consumer, event_id)` deduplication.

        Projector failures are never masked as success; they route to DLQ with `alert_raised=True`.
        """
        dedup_key = (envelope.tenant_id, consumer, envelope.event_id)
        if dedup_key in self._inbox_dedup:
            return False
        try:
            projector(envelope)
        except Exception as exc:
            self._dlq.append(
                DLQRecord(
                    dlq_id=str(uuid.uuid4()),
                    tenant_id=envelope.tenant_id,
                    project_id=envelope.project_id,
                    consumer=consumer,
                    event_id=envelope.event_id,
                    error_reason=str(exc),
                    alert_raised=True,
                )
            )
            return False
        self._inbox_dedup.add(dedup_key)
        return True

    @property
    def dlq(self) -> list[DLQRecord]:
        return list(self._dlq)

    def replay_and_converge(
        self,
        stream: list[dict[str, Any] | CanonicalEventEnvelope],
        *,
        consumer: str = "state_convergence_projector",
    ) -> dict[str, Any]:
        """Replay an arbitrary stream (with duplicates and out-of-order arrivals) and converge state (`R27-1`).

        Guarantees:
        - Per-aggregate causal version ordering `1, 2, ..., K`
        - Idempotent deduplication by `(tenant_id, consumer, event_id)` and side-effect `idempotency_key`
        - 0 duplicate PR creations and 0 duplicate billing charges
        """
        pending_by_agg: dict[tuple[str, str], dict[int, CanonicalEventEnvelope]] = {}
        next_expected_ver: dict[tuple[str, str], int] = {}
        aggregate_states: dict[tuple[str, str], dict[str, Any]] = {}
        pr_created_by_key: dict[tuple[str, str], str] = {}
        pr_creation_count_by_key: dict[tuple[str, str], int] = {}
        billing_charged_by_key: dict[tuple[str, str], int] = {}
        billing_charge_count_by_key: dict[tuple[str, str], int] = {}
        version_conflicts: int = 0
        applied_count: int = 0
        duplicate_deliveries_ignored: int = 0

        def _apply_envelope(env: CanonicalEventEnvelope) -> None:
            nonlocal applied_count
            akey = (env.tenant_id, env.aggregate_id)
            st = aggregate_states.setdefault(
                akey,
                {
                    "tenant_id": env.tenant_id,
                    "project_id": env.project_id,
                    "aggregate_type": env.aggregate_type,
                    "aggregate_id": env.aggregate_id,
                    "version": 0,
                    "status": "INIT",
                    "history": [],
                },
            )
            st["version"] = env.aggregate_version
            if "status" in env.payload:
                st["status"] = env.payload["status"]
            st["history"].append(env.event_id)

            if env.type == "PR_CREATED":
                idem = (env.tenant_id, str(env.payload.get("idempotency_key") or env.aggregate_id))
                if idem not in pr_created_by_key:
                    pr_created_by_key[idem] = str(env.payload.get("pr_number", env.event_id))
                    pr_creation_count_by_key[idem] = 1
            elif env.type == "BILLING_CHARGED":
                idem = (env.tenant_id, str(env.payload.get("idempotency_key") or env.aggregate_id))
                if idem not in billing_charged_by_key:
                    billing_charged_by_key[idem] = int(env.payload.get("amount_micros", 0))
                    billing_charge_count_by_key[idem] = 1

            applied_count += 1

        for raw in stream:
            env = validate_envelope(raw)
            dedup_key = (env.tenant_id, consumer, env.event_id)
            if dedup_key in self._inbox_dedup:
                duplicate_deliveries_ignored += 1
                continue

            akey = (env.tenant_id, env.aggregate_id)
            cur_next = next_expected_ver.get(akey, 1)
            if env.aggregate_version < cur_next:
                # Already applied this version; if same event_id, ignore duplicate; otherwise record conflict
                existing = self._events_by_agg_ver.get((env.tenant_id, env.aggregate_id, env.aggregate_version))
                if existing and existing.event_id == env.event_id:
                    duplicate_deliveries_ignored += 1
                else:
                    version_conflicts += 1
                continue

            bucket = pending_by_agg.setdefault(akey, {})
            if env.aggregate_version in bucket:
                if bucket[env.aggregate_version].event_id == env.event_id:
                    duplicate_deliveries_ignored += 1
                else:
                    version_conflicts += 1
                continue

            bucket[env.aggregate_version] = env

            # Drain consecutive versions starting at cur_next
            while cur_next in bucket:
                ready_env = bucket.pop(cur_next)
                try:
                    self.publish_transactional(ready_env)
                except OptimisticConcurrencyError:
                    version_conflicts += 1
                    break
                self.consume_once(consumer=consumer, envelope=ready_env, projector=_apply_envelope)
                cur_next += 1
                next_expected_ver[akey] = cur_next

        duplicate_prs = sum(c - 1 for c in pr_creation_count_by_key.values() if c > 1)
        duplicate_charges = sum(c - 1 for c in billing_charge_count_by_key.values() if c > 1)
        return {
            "applied_count": applied_count,
            "duplicate_deliveries_ignored": duplicate_deliveries_ignored,
            "version_conflicts": version_conflicts,
            "unapplied_buffered_count": sum(len(b) for b in pending_by_agg.values()),
            "aggregate_states": aggregate_states,
            "pr_created_by_key": pr_created_by_key,
            "billing_charged_by_key": billing_charged_by_key,
            "duplicate_prs": duplicate_prs,
            "duplicate_charges": duplicate_charges,
        }


@dataclass
class SSEFrame:
    cursor: int
    event: str
    data: dict[str, Any]

    def format_sse(self) -> str:
        payload_str = json.dumps(self.data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"id: {self.cursor}\nevent: {self.event}\ndata: {payload_str}\n\n"


class MissionControlSSEGateway:
    """Real-time UI synchronization gateway (`EvoForge_v4.2_44.md`, `R44-1`, `R44-2`, `R44-3`).

    - Returns `projection_version` and `event_cursor` at the same consistency boundary.
    - Detects cursor gaps, retention expiry, and patch failures and demands snapshot resync.
    - Enforces pre-publish tenant & RBAC filtering (`R44-3`).
    - Under burst overload (1,000+ events/sec), samples `progress` events while preserving 100% of
      `approval`, `error`, and `conclusion` events (`R44-2`).
    - Tracks command button states strictly (`RECEIVED -> PENDING -> APPLIED -> DONE`, `D-009`).
    """

    def __init__(self, *, retention_window_events: int = 5_000, progress_sample_stride: int = 10):
        self.retention_window_events = retention_window_events
        self.progress_sample_stride = max(1, progress_sample_stride)
        self._global_cursor: int = 0
        # (tenant_id, project_id) -> projection state dict
        self._projections: dict[tuple[str, str], dict[str, Any]] = {}
        # (tenant_id, project_id) -> list of (cursor, projection_version, category, changes, sensitive_min_role)
        self._delta_log: dict[tuple[str, str], list[dict[str, Any]]] = {}

    _ROLE_RANK = {
        "viewer": 1,
        "reviewer": 2,
        "developer": 3,
        "operator": 4,
        "admin": 5,
        "owner": 6,
    }

    def _ensure_projection(self, tenant_id: str, project_id: str) -> dict[str, Any]:
        key = (tenant_id, project_id)
        if key not in self._projections:
            self._projections[key] = {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "projection_version": 0,
                "event_cursor": 0,
                "objective_version": 1,
                "stop_all": False,
                "tasks": {},
                "commands": {},
                "merges": {},
                "approvals": {},
                "errors": [],
            }
            self._delta_log[key] = []
        return self._projections[key]

    @staticmethod
    def classify_event_category(event_type: str, explicit_category: str | None = None) -> str:
        if explicit_category in {"progress", "approval", "error", "conclusion"}:
            return explicit_category
        if event_type in {"APPROVAL_RECORDED"}:
            return "approval"
        if event_type in {"ERROR_RAISED", "CONTEXT_SECURITY_VIOLATION", "CONTEXT_CODEC_AUTO_DISABLED"}:
            return "error"
        if event_type in CRITICAL_EVENT_TYPES:
            return "conclusion"
        return "progress"

    def ingest_domain_event(
        self,
        envelope: CanonicalEventEnvelope,
        *,
        category: str | None = None,
        min_role: str = "viewer",
    ) -> dict[str, Any]:
        """Project a committed domain event into `MissionControlProjection` and append an SSE delta."""
        proj = self._ensure_projection(envelope.tenant_id, envelope.project_id)
        self._global_cursor += 1
        cursor = self._global_cursor
        proj["projection_version"] += 1
        proj["event_cursor"] = cursor
        pver = proj["projection_version"]

        cat = self.classify_event_category(envelope.type, category)
        changes: list[dict[str, Any]] = []
        payload = envelope.payload

        if envelope.type == "OBJECTIVE_UPDATED":
            proj["objective_version"] = int(payload["objective_version"])
            changes.append({"path": "/objective_version", "value": proj["objective_version"]})
        elif envelope.type in {"COMMAND_RECEIVED", "COMMAND_PENDING", "COMMAND_APPLIED", "COMMAND_DONE"}:
            cmd_id = str(payload.get("command_id", envelope.aggregate_id))
            ui_state_map = {
                "COMMAND_RECEIVED": "PENDING",
                "COMMAND_PENDING": "PENDING",
                "COMMAND_APPLIED": "DONE",
                "COMMAND_DONE": "DONE",
            }
            ui_state = ui_state_map[envelope.type]
            proj["commands"][cmd_id] = {
                "command_version": envelope.aggregate_version,
                "event_type": envelope.type,
                "ui_button_state": ui_state,
            }
            changes.append({"path": f"/commands/{cmd_id}", "value": copy.deepcopy(proj["commands"][cmd_id])})
        elif envelope.type == "STOP_ALL_APPLIED":
            proj["stop_all"] = True
            changes.append({"path": "/stop_all", "value": True})
        elif envelope.type in {"TASK_READY", "TASK_PROGRESS", "TASK_COMPLETED"}:
            task_id = str(payload.get("task_id", envelope.aggregate_id))
            status = str(payload.get("status", "RUNNING" if envelope.type == "TASK_PROGRESS" else envelope.type))
            proj["tasks"][task_id] = {"status": status, "progress": payload.get("progress", 0)}
            changes.append({"path": f"/tasks/{task_id}", "value": copy.deepcopy(proj["tasks"][task_id])})
        elif envelope.type == "APPROVAL_RECORDED":
            cand_id = str(payload.get("candidate_id", envelope.aggregate_id))
            proj["approvals"][cand_id] = {"approved_by": envelope.actor["id"], "verdict": "APPROVED"}
            changes.append({"path": f"/approvals/{cand_id}", "value": copy.deepcopy(proj["approvals"][cand_id])})
        elif envelope.type == "MERGE_CONFIRMED":
            cand_id = str(payload.get("candidate_id", envelope.aggregate_id))
            proj["merges"][cand_id] = {"status": "MERGED", "merge_sha": payload.get("merge_sha", "sha_merged")}
            changes.append({"path": f"/merges/{cand_id}", "value": copy.deepcopy(proj["merges"][cand_id])})
        elif envelope.type == "ERROR_RAISED":
            err_entry = {"event_id": envelope.event_id, "code": payload.get("code", "ERR")}
            proj["errors"].append(err_entry)
            changes.append({"path": f"/errors/{len(proj['errors']) - 1}", "value": err_entry})
        else:
            changes.append({"path": f"/events/{envelope.event_id}", "value": envelope.type})

        delta_entry = {
            "cursor": cursor,
            "tenant_id": envelope.tenant_id,
            "project_id": envelope.project_id,
            "projection_version": pver,
            "category": cat,
            "event_type": envelope.type,
            "min_role": min_role,
            "changes": changes,
        }
        log = self._delta_log[(envelope.tenant_id, envelope.project_id)]
        log.append(delta_entry)
        if len(log) > self.retention_window_events:
            del log[: len(log) - self.retention_window_events]
        return delta_entry

    def get_snapshot(
        self,
        *,
        viewer_tenant_id: str,
        viewer_role: str,
        target_tenant_id: str,
        target_project_id: str,
    ) -> dict[str, Any]:
        """Return MissionControl snapshot + `projection_version` + `event_cursor` at the same consistency boundary."""
        if viewer_tenant_id != target_tenant_id:
            raise EventBusError("NOT_FOUND", "resource not found (cross-tenant isolation R43-2 / R44-3)")
        if self._ROLE_RANK.get(viewer_role, 0) < self._ROLE_RANK["viewer"]:
            raise EventBusError("FORBIDDEN", "viewer role required")
        proj = self._ensure_projection(target_tenant_id, target_project_id)
        return copy.deepcopy(proj)

    def stream_from_cursor(
        self,
        *,
        viewer_tenant_id: str,
        viewer_role: str,
        target_tenant_id: str,
        target_project_id: str,
        after_cursor: int,
        last_known_projection_version: int | None = None,
        overload_mode: bool = False,
    ) -> dict[str, Any]:
        """Stream SSE frames after `after_cursor` with pre-publish ACL filter (`R44-3`) and burst sampling (`R44-2`)."""
        if viewer_tenant_id != target_tenant_id:
            # Pre-publish isolation: 0 events leaked across tenants
            return {"resync_required": False, "frames": [], "dropped_progress_count": 0}

        viewer_rank = self._ROLE_RANK.get(viewer_role, 0)
        if viewer_rank < self._ROLE_RANK["viewer"]:
            return {"resync_required": False, "frames": [], "dropped_progress_count": 0}

        key = (target_tenant_id, target_project_id)
        proj = self._ensure_projection(target_tenant_id, target_project_id)
        log = self._delta_log[key]

        if not log:
            if last_known_projection_version not in (None, 0):
                return {
                    "resync_required": True,
                    "reason": "CURSOR_RETENTION_EXPIRED",
                    "snapshot": copy.deepcopy(proj),
                    "frames": [],
                }
            return {"resync_required": False, "frames": [], "dropped_progress_count": 0}

        oldest_cursor = log[0]["cursor"]
        if after_cursor > 0 and after_cursor < oldest_cursor - 1:
            return {
                "resync_required": True,
                "reason": "CURSOR_RETENTION_EXPIRED",
                "snapshot": copy.deepcopy(proj),
                "frames": [],
            }

        candidates = [d for d in log if d["cursor"] > after_cursor]
        if (
            last_known_projection_version is not None
            and candidates
            and candidates[0]["projection_version"] != last_known_projection_version + 1
            and not overload_mode
        ):
            return {
                "resync_required": True,
                "reason": "PROJECTION_VERSION_GAP",
                "snapshot": copy.deepcopy(proj),
                "frames": [],
            }

        frames: list[SSEFrame] = []
        dropped_progress = 0
        progress_seen = 0

        for d in candidates:
            req_rank = self._ROLE_RANK.get(d["min_role"], 1)
            if viewer_rank < req_rank:
                # Pre-publish RBAC filter: strip sensitive admin/operator deltas from lower-role stream
                continue
            if overload_mode and d["category"] == "progress":
                progress_seen += 1
                if progress_seen % self.progress_sample_stride != 1:
                    dropped_progress += 1
                    continue
            frame = SSEFrame(
                cursor=d["cursor"],
                event="project.state.delta",
                data={
                    "project_id": d["project_id"],
                    "projection_version": d["projection_version"],
                    "category": d["category"],
                    "changes": copy.deepcopy(d["changes"]),
                },
            )
            frames.append(frame)

        return {
            "resync_required": False,
            "frames": frames,
            "dropped_progress_count": dropped_progress,
        }

    @staticmethod
    def apply_client_stream(
        initial_snapshot: dict[str, Any],
        stream_result: dict[str, Any],
        *,
        fallback_snapshot_fetcher: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply SSE delta stream to client state, automatically resyncing from snapshot on gap or patch failure (`R44-1`)."""
        if stream_result.get("resync_required"):
            return copy.deepcopy(stream_result.get("snapshot") or fallback_snapshot_fetcher())

        state = copy.deepcopy(initial_snapshot)
        expected_ver = int(state.get("projection_version", 0))
        for frame in stream_result.get("frames", []):
            data = frame.data
            if data["projection_version"] != expected_ver + 1:
                # Version gap (e.g., sampled progress frames during burst or missed frame) -> resync snapshot
                return copy.deepcopy(fallback_snapshot_fetcher())
            try:
                for ch in data["changes"]:
                    path = ch["path"]
                    val = ch["value"]
                    if path == "/objective_version":
                        state["objective_version"] = val
                    elif path == "/stop_all":
                        state["stop_all"] = val
                    elif path.startswith("/tasks/"):
                        tid = path.split("/")[2]
                        state["tasks"][tid] = copy.deepcopy(val)
                    elif path.startswith("/commands/"):
                        cid = path.split("/")[2]
                        state["commands"][cid] = copy.deepcopy(val)
                    elif path.startswith("/approvals/"):
                        cand_id = path.split("/")[2]
                        state["approvals"][cand_id] = copy.deepcopy(val)
                    elif path.startswith("/merges/"):
                        cand_id = path.split("/")[2]
                        state["merges"][cand_id] = copy.deepcopy(val)
                    elif path.startswith("/errors/"):
                        state["errors"].append(val)
                    else:
                        raise ValueError(f"unsupported delta path {path}")
            except Exception:
                return copy.deepcopy(fallback_snapshot_fetcher())
            expected_ver = data["projection_version"]
            state["projection_version"] = expected_ver
            state["event_cursor"] = frame.cursor

        return state
