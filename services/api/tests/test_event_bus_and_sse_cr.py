"""Acceptance tests for DomainEventBus, Outbox/Inbox deduplication, 10k replay convergence, and SSE Gateway (R27-1..3, R44-1..3)."""

from __future__ import annotations

import os
import random
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evoforge.event_bus_and_sse import (
    ArtifactFirstHandoff,
    CanonicalTrajectoryNormalizer,
    DomainEventBus,
    EventBusError,
    MissionControlSSEGateway,
    OptimisticConcurrencyError,
)


TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"
PROJECT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _make_event(
    *,
    event_id: str | None = None,
    tenant_id: str = TENANT_A,
    project_id: str = PROJECT_A,
    event_type: str = "TASK_PROGRESS",
    aggregate_type: str = "task",
    aggregate_id: str = "task-1",
    aggregate_version: int = 1,
    actor_kind: str = "operator",
    actor_id: str = "user-1",
    message_kind: str = "EVENT",
    payload: dict | None = None,
) -> dict:
    eid = event_id or str(uuid.uuid4())
    return {
        "event_id": eid,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "type": event_type,
        "schema_version": "event-envelope/v1",
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "aggregate_version": aggregate_version,
        "correlation_id": f"corr-{aggregate_id}",
        "causation_id": f"caus-{aggregate_id}-{aggregate_version}",
        "trace_id": f"trace-{aggregate_id}",
        "actor": {"kind": actor_kind, "id": actor_id},
        "occurred_at": "2026-10-27T12:00:00Z",
        "payload": payload if payload is not None else {"status": "RUNNING"},
        "message_kind": message_kind,
    }


def test_domain_event_envelope_optimistic_concurrency_and_command_proposal_separation_r27_2() -> None:
    """R27-2 (C-11): Same aggregate version conflict rejects second event; COMMAND vs PROPOSAL separation enforced."""
    bus = DomainEventBus()

    ev1 = _make_event(event_id="ev-v1-winner", aggregate_id="agg-42", aggregate_version=1)
    stored = bus.publish_transactional(ev1)
    assert stored.event_id == "ev-v1-winner"

    # Idempotent re-publish of the same event_id succeeds without duplicate outbox entry
    re_stored = bus.publish_transactional(ev1)
    assert re_stored.event_id == "ev-v1-winner"
    assert len(bus._outbox) == 1

    # Conflicting event at the same (tenant_id, aggregate_id, aggregate_version) must fail (R27-2, C-11)
    ev1_conflict = _make_event(event_id="ev-v1-loser", aggregate_id="agg-42", aggregate_version=1)
    with pytest.raises(OptimisticConcurrencyError) as exc_info:
        bus.publish_transactional(ev1_conflict)
    assert exc_info.value.code == "AGGREGATE_VERSION_CONFLICT"

    # AI actors cannot emit COMMAND messages directly; must use PROPOSAL
    ai_cmd = _make_event(
        actor_kind="ai_agent",
        actor_id="seat-builder-alpha",
        message_kind="COMMAND",
        aggregate_version=2,
    )
    with pytest.raises(EventBusError) as exc_cmd:
        bus.publish_transactional(ai_cmd)
    assert exc_cmd.value.code == "COMMAND_PROPOSAL_MIX_FORBIDDEN"

    ai_proposal = _make_event(
        actor_kind="ai_agent",
        actor_id="seat-builder-alpha",
        message_kind="PROPOSAL",
        aggregate_id="agg-42",
        aggregate_version=2,
    )
    assert bus.publish_transactional(ai_proposal).message_kind == "PROPOSAL"

    # Artifact-first handoff rejects sequential refs (CR-31) and oversized inline blobs
    handoff = ArtifactFirstHandoff(max_inline_bytes=128)
    with pytest.raises(EventBusError) as exc_ref:
        handoff.build_handoff(
            tenant_id=TENANT_A,
            artifact_uri="s3://vault/diff.patch",
            content_bytes=b"diff content",
            base_sha="abc12345",
            acceptance_criteria=["pytest -q"],
            replay_steps=["git apply diff.patch"],
            evidence_ref="ref_0001",  # sequential ref
        )
    assert exc_ref.value.code == "SEQUENTIAL_OR_INVALID_REF"

    valid_ho = handoff.build_handoff(
        tenant_id=TENANT_A,
        artifact_uri="s3://vault/diff.patch",
        content_bytes=b"diff content",
        base_sha="abc12345",
        acceptance_criteria=["pytest -q"],
        replay_steps=["git apply diff.patch"],
        evidence_ref="ef_ref_9f8a7b6c5d4e3f2a1b0c9d8e",
        inline_preview="short summary",
    )
    assert valid_ho["ref"] == "ef_ref_9f8a7b6c5d4e3f2a1b0c9d8e"

    # Canonical Trajectory v1 normalization across API, Chat, and CLI
    norm_turn = CanonicalTrajectoryNormalizer.normalize_record(
        "chat", {"kind": "assistant_message", "run_id": "r1", "task_id": "t1", "summary": "planned"}
    )
    norm_tool = CanonicalTrajectoryNormalizer.normalize_record(
        "cli", {"kind": "function_call", "run_id": "r1", "task_id": "t1", "summary": "pytest"}
    )
    norm_cost = CanonicalTrajectoryNormalizer.normalize_record(
        "api", {"kind": "usage_receipt", "run_id": "r1", "task_id": "t1", "cost_micros": 4200}
    )
    assert (norm_turn["kind"], norm_tool["kind"], norm_cost["kind"]) == ("turn", "tool_call", "cost")


def test_event_bus_10k_replay_duplicate_and_out_of_order_convergence_r27_1() -> None:
    """R27-1: 10,000-event stream with duplicates and out-of-order arrivals converges with 0 duplicate PRs/charges."""
    bus = DomainEventBus()
    rng = random.Random(20261027)

    # Create 200 aggregates x 35 versions = 7,000 unique causal events + 3,000 duplicates = 10,000 events
    unique_events: list[dict] = []
    for agg_idx in range(200):
        agg_id = f"agg-{agg_idx:03d}"
        for ver in range(1, 36):
            if ver == 34:
                ev_type = "PR_CREATED"
                payload = {"status": "PR_OPEN", "idempotency_key": f"pr:{agg_id}", "pr_number": 1000 + agg_idx}
            elif ver == 35:
                ev_type = "BILLING_CHARGED"
                payload = {"status": "DONE", "idempotency_key": f"bill:{agg_id}", "amount_micros": 5000}
            else:
                ev_type = "TASK_PROGRESS"
                payload = {"status": f"STEP_{ver}", "progress": ver}
            unique_events.append(
                _make_event(
                    event_id=f"ev-{agg_id}-v{ver}",
                    event_type=ev_type,
                    aggregate_id=agg_id,
                    aggregate_version=ver,
                    payload=payload,
                )
            )

    duplicates = [rng.choice(unique_events) for _ in range(3_000)]
    stream_10k = unique_events + duplicates
    assert len(stream_10k) == 10_000
    rng.shuffle(stream_10k)

    result = bus.replay_and_converge(stream_10k, consumer="convergence_v1")
    assert result["applied_count"] == 7_000
    assert result["duplicate_deliveries_ignored"] == 3_000
    assert result["unapplied_buffered_count"] == 0
    assert result["version_conflicts"] == 0
    assert result["duplicate_prs"] == 0
    assert result["duplicate_charges"] == 0
    assert len(result["pr_created_by_key"]) == 200
    assert len(result["billing_charged_by_key"]) == 200

    for agg_idx in range(200):
        agg_id = f"agg-{agg_idx:03d}"
        st = result["aggregate_states"][(TENANT_A, agg_id)]
        assert st["version"] == 35
        assert st["status"] == "DONE"

    # Projector failure routes to DLQ with alert_raised=True and does not mark consumed
    bad_env = bus.publish_transactional(
        _make_event(event_id="ev-dlq-test", aggregate_id="agg-dlq", aggregate_version=1)
    )
    ok = bus.consume_once(
        consumer="failing_projector",
        envelope=bad_env,
        projector=lambda _e: (_ for _ in ()).throw(RuntimeError("projector db timeout")),
    )
    assert ok is False
    assert len(bus.dlq) == 1
    assert bus.dlq[0].event_id == "ev-dlq-test"
    assert bus.dlq[0].alert_raised is True


def test_sse_projection_multi_client_convergence_and_snapshot_resync_r44_1() -> None:
    """R44-1 & D-009: Multi-client (browser/mobile) disconnect/reconnect convergence and command UI states."""
    bus = DomainEventBus()
    sse = MissionControlSSEGateway(retention_window_events=4)

    def _emit(ev_dict: dict) -> None:
        env = bus.publish_transactional(ev_dict)
        sse.ingest_domain_event(env)

    _emit(_make_event(event_id="e1", event_type="OBJECTIVE_UPDATED", aggregate_id="obj-1", aggregate_version=1, payload={"objective_version": 2}))
    _emit(_make_event(event_id="e2", event_type="COMMAND_RECEIVED", aggregate_id="cmd-1", aggregate_version=1, payload={"command_id": "cmd-1"}))

    # Browser client connects at cursor 2; verify COMMAND_RECEIVED shows PENDING (not DONE)
    browser_snap = sse.get_snapshot(
        viewer_tenant_id=TENANT_A, viewer_role="viewer", target_tenant_id=TENANT_A, target_project_id=PROJECT_A
    )
    assert browser_snap["projection_version"] == 2
    assert browser_snap["event_cursor"] == 2
    assert browser_snap["commands"]["cmd-1"]["ui_button_state"] == "PENDING"

    # Mobile client connects earlier at cursor 1
    mobile_cursor = 1

    # Server progresses: command applied, task completed, approval + merge confirmed
    _emit(_make_event(event_id="e3", event_type="COMMAND_APPLIED", aggregate_id="cmd-1", aggregate_version=2, payload={"command_id": "cmd-1"}))
    _emit(_make_event(event_id="e4", event_type="TASK_COMPLETED", aggregate_id="task-1", aggregate_version=1, payload={"task_id": "task-1", "status": "COMPLETED"}))
    _emit(_make_event(event_id="e5", event_type="APPROVAL_RECORDED", aggregate_id="cand-1", aggregate_version=1, payload={"candidate_id": "cand-1"}))
    _emit(_make_event(event_id="e6", event_type="MERGE_CONFIRMED", aggregate_id="cand-1", aggregate_version=2, payload={"candidate_id": "cand-1", "merge_sha": "sha_999"}))

    # Browser streams cleanly from cursor 2 (within retention window of 5: cursors 2..6 are retained)
    browser_stream = sse.stream_from_cursor(
        viewer_tenant_id=TENANT_A,
        viewer_role="viewer",
        target_tenant_id=TENANT_A,
        target_project_id=PROJECT_A,
        after_cursor=browser_snap["event_cursor"],
        last_known_projection_version=browser_snap["projection_version"],
    )
    assert browser_stream["resync_required"] is False
    assert len(browser_stream["frames"]) == 4
    assert "event: project.state.delta" in browser_stream["frames"][0].format_sse()

    fetcher = lambda: sse.get_snapshot(
        viewer_tenant_id=TENANT_A, viewer_role="viewer", target_tenant_id=TENANT_A, target_project_id=PROJECT_A
    )
    browser_final = sse.apply_client_stream(browser_snap, browser_stream, fallback_snapshot_fetcher=fetcher)

    # Mobile cursor=1 fell outside the 5-event retention window (oldest retained is cursor 2) -> resync_required
    mobile_stream = sse.stream_from_cursor(
        viewer_tenant_id=TENANT_A,
        viewer_role="viewer",
        target_tenant_id=TENANT_A,
        target_project_id=PROJECT_A,
        after_cursor=mobile_cursor,
        last_known_projection_version=1,
    )
    assert mobile_stream["resync_required"] is True
    assert mobile_stream["reason"] == "CURSOR_RETENTION_EXPIRED"
    mobile_final = sse.apply_client_stream({}, mobile_stream, fallback_snapshot_fetcher=fetcher)

    # Both browser and mobile converge to the exact same final state
    assert browser_final == mobile_final
    assert browser_final["commands"]["cmd-1"]["ui_button_state"] == "DONE"
    assert browser_final["merges"]["cand-1"]["status"] == "MERGED"


def test_sse_1000_events_burst_zero_critical_drop_and_acl_filter_r44_2_r44_3() -> None:
    """R44-2 & R44-3: Under 1,000 events/sec burst, approval/error/conclusion drops = 0; cross-tenant/unauthorized = 0."""
    bus = DomainEventBus()
    sse = MissionControlSSEGateway(retention_window_events=2_000, progress_sample_stride=20)

    expected_critical_Count = 0
    for i in range(1, 1001):
        if i % 50 == 0:
            ev_type = "APPROVAL_RECORDED"
            expected_critical_Count += 1
            min_role = "viewer"
        elif i % 33 == 0:
            ev_type = "ERROR_RAISED"
            expected_critical_Count += 1
            min_role = "viewer"
        elif i % 25 == 0:
            ev_type = "MERGE_CONFIRMED"
            expected_critical_Count += 1
            min_role = "viewer"
        elif i == 777:
            ev_type = "TASK_PROGRESS"
            min_role = "admin"  # Admin-only sensitive progress event
        else:
            ev_type = "TASK_PROGRESS"
            min_role = "viewer"

        env = bus.publish_transactional(
            _make_event(
                event_id=f"burst-{i}",
                event_type=ev_type,
                aggregate_id=f"agg-{i}",
                aggregate_version=1,
                payload={"task_id": f"t-{i}", "candidate_id": f"c-{i}", "code": "E_TEST"},
            )
        )
        sse.ingest_domain_event(env, min_role=min_role)

    # Cross-tenant viewer receives 0 events (R44-3)
    cross_tenant = sse.stream_from_cursor(
        viewer_tenant_id=TENANT_B,
        viewer_role="owner",
        target_tenant_id=TENANT_A,
        target_project_id=PROJECT_A,
        after_cursor=0,
        overload_mode=True,
    )
    assert len(cross_tenant["frames"]) == 0

    # Authorized viewer in overload_mode receives sampled progress events AND 100% of critical events (R44-2)
    burst_stream = sse.stream_from_cursor(
        viewer_tenant_id=TENANT_A,
        viewer_role="viewer",
        target_tenant_id=TENANT_A,
        target_project_id=PROJECT_A,
        after_cursor=0,
        overload_mode=True,
    )
    assert burst_stream["dropped_progress_count"] > 800
    delivered_critical = [
        f for f in burst_stream["frames"] if f.data["category"] in {"approval", "error", "conclusion"}
    ]
    assert len(delivered_critical) == expected_critical_Count
