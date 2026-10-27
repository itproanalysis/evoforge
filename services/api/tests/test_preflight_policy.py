"""Provider permission and consent must never fail open on malformed input."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[1]
_ROOT = _API.parents[1]
sys.path.insert(0, str(_API))

from evoforge.eval_runner_and_preflight import PreflightCallBroker, PreflightError  # noqa: E402
from evoforge.reconciler_policy import ReconcilerLedger  # noqa: E402


@pytest.fixture
def setup_call():
    packet = json.loads((_ROOT / "docs/evoforge-v4.2/contracts/examples/valid/context-packet.builder.json")
                        .read_text(encoding="utf-8"))
    ledger = ReconcilerLedger()
    ledger.set_project_budget(packet["tenant_id"], packet["project_id"], "2026-10-01", 100_000)
    ledger.grant_credit(packet["tenant_id"], 200_000, idempotency_key="synthetic-credit")

    def make(allowed):
        broker = PreflightCallBroker(ledger, allowed_providers=allowed,
                                     server_now=lambda: datetime(2026, 10, 25, 9, 30, tzinfo=timezone.utc))
        broker.register_lease(packet["run_id"], packet["task_id"], packet["recipient"]["agent_id"],
                              lease_epoch=packet["fencing"]["lease_epoch"])
        return broker

    return packet, ledger, make


def test_empty_provider_allowlist_denies_without_reservation(setup_call):
    packet, ledger, make = setup_call
    broker = make(set())
    broker.set_provider_consent(packet["tenant_id"], packet["cache_plan"]["provider"])
    with pytest.raises(PreflightError) as error:
        broker.prebind_and_reserve(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000)
    assert error.value.code == "PROVIDER_NOT_ALLOWED"
    assert not ledger._reservations and not ledger._intents


@pytest.mark.parametrize("value", [None, False, "false", 1, 0, {}])
def test_only_boolean_true_is_consent_even_if_state_is_corrupt(setup_call, value):
    packet, ledger, make = setup_call
    provider = packet["cache_plan"]["provider"]
    broker = make({provider})
    broker.provider_consents[(packet["tenant_id"], provider)] = value
    with pytest.raises(PreflightError) as error:
        broker.prebind_and_reserve(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000)
    assert error.value.code == "PROVIDER_CONSENT_MISSING"
    assert not ledger._reservations


@pytest.mark.parametrize("value", [None, "false", 0, 1, [], {}])
def test_consent_setter_rejects_non_booleans(setup_call, value):
    packet, _, make = setup_call
    broker = make(None)
    with pytest.raises((TypeError, ValueError)):
        broker.set_provider_consent(packet["tenant_id"], packet["cache_plan"]["provider"], consented=value)
    assert not broker.provider_consents


@pytest.mark.parametrize("allowed", ["openai", ["openai"], {"openai", 1}])
def test_malformed_allowlist_is_rejected(setup_call, allowed):
    _, _, make = setup_call
    with pytest.raises((TypeError, ValueError)):
        make(allowed)


def test_default_allowlist_and_true_consent_remain_usable(setup_call):
    packet, ledger, make = setup_call
    broker = make(None)
    broker.set_provider_consent(packet["tenant_id"], packet["cache_plan"]["provider"], consented=True)
    binding = broker.prebind_and_reserve(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000)
    assert ledger._reservations[(packet["tenant_id"], packet["project_id"], binding.call_id)].status == "RESERVED"
