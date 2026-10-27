"""Acceptance tests for M0 Hygiene Eval Runner and Broker/CLI Preflight Guard (CR-29, CR-33, CR-37, CR-38, CR-41, CR-74)."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evoforge.eval_runner_and_preflight import (  # noqa: E402
    DevBuilderCLIGuard,
    HygieneEvalRunner,
    PreflightCallBroker,
    PreflightError,
)
from evoforge.reconciler_policy import ReconcilerLedger  # noqa: E402

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_EXAMPLES_DIR = os.path.join(_ROOT, "docs", "evoforge-v4.2", "contracts", "examples")

TENANT_ID = "6f1d2c3b-0a00-4b1e-9c2d-0000000000a1"
PROJECT_ID = "6f1d2c3b-0a00-4b1e-9c2d-0000000000b1"
RUN_ID = "0b7e1f00-1111-4c22-8d33-000000000001"
TASK_ID = "0b7e1f00-1111-4c22-8d33-000000000002"
AGENT_ID = "0b7e1f00-1111-4c22-8d33-0000000000a2"
PERIOD = "2026-10-01"


def _make_git_test_repo() -> tuple[str, str, str, str]:
    """Build a repo with a base commit and a future commit containing a secret token."""
    tmp = tempfile.mkdtemp(prefix="evoforge-test-git-")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="EvoForge", GIT_AUTHOR_EMAIL="dev@evoforge.local",
               GIT_COMMITTER_NAME="EvoForge", GIT_COMMITTER_EMAIL="dev@evoforge.local")
    subprocess.run(["git", "init", "-q", tmp], check=True, env=env)
    app_py = os.path.join(tmp, "app.py")
    with open(app_py, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("def solve():\n    return 41\n")
    subprocess.run(["git", "add", "app.py"], cwd=tmp, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "base commit"], cwd=tmp, check=True, env=env)
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp, check=True, env=env, capture_output=True, text=True).stdout.strip()

    secret_token = "FUTURE_SECRET_TOKEN_XYZ_888"
    with open(os.path.join(tmp, "secret.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"leaked secret: {secret_token}\n")
    subprocess.run(["git", "add", "secret.txt"], cwd=tmp, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "future secret commit"], cwd=tmp, check=True, env=env)
    future_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp, check=True, env=env, capture_output=True, text=True).stdout.strip()

    return tmp, base_sha, future_sha, secret_token


def _load_example_packet() -> dict:
    with open(os.path.join(_EXAMPLES_DIR, "valid", "context-packet.builder.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_hygiene_sandbox_isolation_and_secret_leak_cr74() -> None:
    """CR-74: Clean sandbox build strips future commits, reflogs, and prevents secret leakage unlike naive clone."""
    source_repo, base_sha, future_sha, secret_token = _make_git_test_repo()
    runner = HygieneEvalRunner()

    res = runner.verify_naive_clone_vs_hygiene_sandbox(
        source_repo=source_repo,
        base_sha=base_sha,
        future_shas=[future_sha],
        secret_token_in_future=secret_token,
    )

    # Naive clone contains future commits / reflog violations and leaks the secret in object database
    assert len(res["naive_violations"]) > 0
    assert any("future commit" in v or "reflog" in v for v in res["naive_violations"])

    # Clean sandbox passes all 7 hygiene checks and strips all future commits and blobs
    assert len(res["clean_violations"]) == 0
    assert all(item["pass"] for item in res["clean_audit"])
    assert res["secret_leaked_in_clean"] is False


def test_hygiene_eval_candidate_execution_and_scaffold_cr74() -> None:
    """CR-74: Evaluation runner in clean sandbox executes test suites, applies gates, and emits 5-field scaffold record."""
    source_repo, base_sha, future_sha, _ = _make_git_test_repo()
    runner = HygieneEvalRunner()

    diff = """--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def solve():\n-    return 41\n+    return 42\n"""
    visible_tests = [
        {"name": "test_vis_1", "kind": "visible", "code": "from app import solve\ndef test_solve(): assert solve() == 42\n"}
    ]
    heldout_tests = [
        {"name": "test_held_1", "kind": "compositional", "code": "from app import solve\ndef test_solve_held(): assert solve() + 1 == 43\n"},
        {"name": "test_held_2", "kind": "negative", "code": "from app import solve\ndef test_solve_neg(): assert solve() != 41\n"},
        {"name": "test_held_3", "kind": "boundary", "code": "from app import solve\ndef test_solve_bound(): assert isinstance(solve(), int)\n"},
    ]

    outcome = runner.evaluate_candidate_in_sandbox(
        task_id="task_hyg_001",
        source_repo=source_repo,
        base_sha=base_sha,
        diff=diff,
        visible_tests=visible_tests,
        heldout_tests=heldout_tests,
        future_shas=[future_sha],
    )

    assert outcome.task_id == "task_hyg_001"
    assert len(outcome.hygiene_violations) == 0
    assert all(a["pass"] for a in outcome.pre_audit)
    assert all(a["pass"] for a in outcome.post_audit)
    assert outcome.visible["pass"] == 1
    assert outcome.heldout["pass"] == 3

    # Gates verdicts include GH_INTEGRITY and G2_REQUIRED
    v_map = {v.gate: v.result for v in outcome.verdicts}
    assert v_map.get("GH_INTEGRITY") == "PASS"
    assert v_map.get("G2_REQUIRED") == "PASS"

    # Mandatory 5-field scaffold score record
    assert outcome.score_row["score"] == 1.0
    sc = outcome.score_row["scaffold"]
    for f in ("name", "version", "turn_cap", "model", "harness_version"):
        assert f in sc and sc[f] is not None


def test_preflight_broker_packet_and_registry_rules_cr29_cr33() -> None:
    """CR-29, CR-33: Broker blocks undisableable provider caching in A0/NONE and blocks stale registry entries."""
    eng = ReconcilerLedger()
    broker = PreflightCallBroker(ledger=eng)

    # Valid packet passes validation
    valid_packet = _load_example_packet()
    broker.validate_packet_and_registry(valid_packet)

    # CR-29: Reject nocache / cache_mode="NONE" on provider where caching cannot be disabled
    with open(os.path.join(_EXAMPLES_DIR, "invalid", "nocache_on_undisableable_provider.json"), encoding="utf-8") as fh:
        nocache_bad = json.load(fh)
    with pytest.raises(PreflightError) as exc_info:
        broker.validate_packet_and_registry(nocache_bad)
    assert exc_info.value.code in ("CACHE_DISABLE_UNSUPPORTED", "PACKET_SEMANTIC_INVALID")

    # CR-33: Reject stale registry entry (> 14 days old)
    with open(os.path.join(_EXAMPLES_DIR, "invalid", "stale_registry_entry.json"), encoding="utf-8") as fh:
        stale_bad = json.load(fh)
    with pytest.raises(PreflightError) as exc_info:
        broker.validate_packet_and_registry(stale_bad)
    assert exc_info.value.code in ("REGISTRY_ENTRY_STALE", "PACKET_SEMANTIC_INVALID")


def test_preflight_broker_reservation_fencing_and_receipt_settlement_cr37_cr38_cr41() -> None:
    """CR-37, CR-38, CR-41: Atomic budget reservation, provider consent/lease fencing, BYOK rejection, and settlement."""
    eng = ReconcilerLedger()
    eng.set_project_budget(TENANT_ID, PROJECT_ID, PERIOD, 500_000)
    eng.grant_credit(TENANT_ID, 1_000_000, idempotency_key="credit:init")

    broker = PreflightCallBroker(ledger=eng, allowed_providers={"meta", "anthropic", "openai"})
    packet = _load_example_packet()
    provider = packet["cache_plan"]["provider"]
    model = packet["cache_plan"]["model"]

    # 1. Provider allow-list check
    bad_provider_pkt = copy.deepcopy(packet)
    bad_provider_pkt["cache_plan"]["provider"] = "untrusted_cloud"
    with pytest.raises(PreflightError, match="PROVIDER_NOT_ALLOWED|PACKET_SCHEMA_INVALID"):
        broker.prebind_and_reserve(call_id=str(uuid.uuid4()), packet=bad_provider_pkt, reserved_micros=10_000)

    # 2. Provider data consent check
    call_id = str(uuid.uuid4())
    with pytest.raises(PreflightError) as exc_info:
        broker.prebind_and_reserve(call_id=call_id, packet=packet, reserved_micros=10_000)
    assert exc_info.value.code == "PROVIDER_CONSENT_MISSING"

    broker.set_provider_consent(TENANT_ID, provider, consented=True)

    # 3. Lease fencing: missing lease -> LEASE_INACTIVE, epoch mismatch -> STALE_LEASE
    with pytest.raises(PreflightError) as exc_info:
        broker.prebind_and_reserve(call_id=call_id, packet=packet, reserved_micros=10_000)
    assert exc_info.value.code == "LEASE_INACTIVE"

    broker.register_lease(RUN_ID, TASK_ID, AGENT_ID, lease_epoch=12, active=True)

    # Epoch mismatch in prebinding
    with pytest.raises(PreflightError) as exc_info:
        broker.prebind_and_reserve(call_id=call_id, packet=packet, reserved_micros=10_000, lease_epoch=11)
    assert exc_info.value.code == "STALE_LEASE"

    # 4. Successful prebinding & reservation
    binding = broker.prebind_and_reserve(
        call_id=call_id,
        packet=packet,
        reserved_micros=25_000,
        lease_epoch=12,
        period_start=PERIOD,
    )
    assert binding.call_id == call_id
    assert binding.reservation_key == call_id
    assert binding.reserved_micros == 25_000
    assert eng.tenant_open_reserved_micros(TENANT_ID) == 25_000

    # 5. Receipt verification & settlement:
    # Reject BYOK or billing_owner != "platform" (CR-41)
    byok_receipt = {
        "schema_version": "provider-usage-receipt/v1",
        "receipt_id": str(uuid.uuid4()),
        "tenant_id": TENANT_ID,
        "project_id": PROJECT_ID,
        "packet_id": packet["packet_id"],
        "call_id": call_id,
        "reservation_key": call_id,
        "call_purpose": "task_turn",
        "provider": provider,
        "model": model,
        "source": "provider_billed",
        "billing_owner": "byok",  # Illegal BYOK
        "tokens": {"uncached_input": 100, "cache_write": 0, "cache_read": 0, "output": 50},
        "cost_micros": 1000,
        "customer_price_micros": 1000,
        "currency": "USD",
        "price_table_version": broker.price_table_version,
        "recorded_at": "2026-10-27T12:00:00Z",
        "provider_request_id": "req_byok_1",
        "raw_usage_fields": {},
    }
    with pytest.raises(PreflightError) as exc_info:
        broker.validate_and_settle_receipt(call_id, byok_receipt)
    assert exc_info.value.code == "BYOK_RECEIPT_FORBIDDEN"

    # Reject reservation key mismatch (CR-37)
    bad_key_receipt = copy.deepcopy(byok_receipt)
    bad_key_receipt["billing_owner"] = "platform"
    bad_key_receipt["reservation_key"] = "wrong_reservation_key_12345"
    with pytest.raises(PreflightError) as exc_info:
        broker.validate_and_settle_receipt(call_id, bad_key_receipt)
    assert exc_info.value.code == "RESERVATION_KEY_MISMATCH"

    # Valid receipt settles cleanly
    valid_receipt = copy.deepcopy(bad_key_receipt)
    valid_receipt["reservation_key"] = call_id
    res = broker.validate_and_settle_receipt(call_id, valid_receipt)
    assert res["settlement"]["zero_cost"] is False
    assert res["settlement"]["actual_micros"] == 1000
    assert eng.tenant_open_reserved_micros(TENANT_ID) == 0


def test_dev_builder_cli_guard_budget_governed_cr38() -> None:
    """CR-38: Developer Muse Builder CLI tasks run under atomic budget reservation and canonical receipt settlement."""
    eng = ReconcilerLedger()
    eng.set_project_budget(TENANT_ID, PROJECT_ID, PERIOD, 200_000)
    eng.grant_credit(TENANT_ID, 500_000, idempotency_key="credit:cli:init")

    broker = PreflightCallBroker(ledger=eng)
    packet = _load_example_packet()
    provider = packet["cache_plan"]["provider"]

    broker.set_provider_consent(TENANT_ID, provider, consented=True)
    broker.register_lease(RUN_ID, TASK_ID, AGENT_ID, lease_epoch=12, active=True)

    cli_guard = DevBuilderCLIGuard(broker=broker)

    called = False

    def mock_cli_runner(task_spec: dict) -> dict:
        nonlocal called
        called = True
        return {
            "task_id": task_spec.get("id"),
            "status": "completed",
            "provider_request_id": "req_meta_cli_777",
            "uncached_input_tokens": 1400,
            "cached_read_tokens": 200,
            "output_tokens": 180,
        }

    task_spec = {"id": TASK_ID, "description": "Run Muse Spark CLI improvement iteration"}
    res = cli_guard.run_cli_task(
        task_spec=task_spec,
        packet=packet,
        reserved_micros=15_000,
        cli_runner=mock_cli_runner,
        actual_micros=8_500,
        period_start=PERIOD,
    )

    assert called is True
    assert res["response"]["status"] == "completed"
    assert res["receipt"]["schema_version"] == "provider-usage-receipt/v1"
    assert res["receipt"]["billing_owner"] == "platform"
    assert res["receipt"]["customer_price_micros"] == 8_500
    assert res["settlement"]["settlement"]["actual_micros"] == 8_500
    assert eng.tenant_open_reserved_micros(TENANT_ID) == 0
