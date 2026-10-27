"""Preflight decisions use the server clock, including immediately before dispatch."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime as RealDatetime, timezone
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[1]
_ROOT = _API.parents[1]
sys.path.insert(0, str(_API))

from evoforge import eval_runner_and_preflight as preflight  # noqa: E402
from evoforge.reconciler_policy import ReconcilerLedger  # noqa: E402


def _clock(monkeypatch, *instants):
    values = iter(instants)
    last = instants[-1]

    class FrozenDatetime(RealDatetime):
        @classmethod
        def now(cls, tz=None):
            instant = next(values, last)
            return instant if tz is None else instant.astimezone(tz)

    monkeypatch.setattr(preflight, "datetime", FrozenDatetime)


def _at(hour, minute, second=0):
    return RealDatetime(2026, 10, 25, hour, minute, second, tzinfo=timezone.utc)


@pytest.fixture
def context():
    packet = json.loads((_ROOT / "docs/evoforge-v4.2/contracts/examples/valid/context-packet.builder.json")
                        .read_text(encoding="utf-8"))
    ledger = ReconcilerLedger()
    ledger.set_project_budget(packet["tenant_id"], packet["project_id"], "2026-10-01", 100_000)
    ledger.grant_credit(packet["tenant_id"], 200_000, idempotency_key="synthetic-credit")
    broker = preflight.PreflightCallBroker(ledger)
    broker.set_provider_consent(packet["tenant_id"], packet["cache_plan"]["provider"])
    broker.register_lease(packet["run_id"], packet["task_id"], packet["recipient"]["agent_id"],
                          lease_epoch=packet["fencing"]["lease_epoch"], expires_at="2026-10-25T11:00:00Z")
    return packet, ledger, broker


@pytest.mark.parametrize("expiry", ["2026-10-25T09:15:00Z", "2026-10-25T11:15:00+02:00"])
def test_expired_lease_is_rejected_at_actual_time_before_reserving(context, monkeypatch, expiry):
    packet, ledger, broker = context
    _clock(monkeypatch, _at(9, 30))
    broker.leases[(packet["run_id"], packet["task_id"])].expires_at = expiry
    with pytest.raises(preflight.PreflightError) as error:
        broker.prebind_and_reserve(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000)
    assert error.value.code == "LEASE_EXPIRED"
    assert not ledger._reservations and not ledger._intents


@pytest.mark.parametrize("now,field,value,code", [
    (_at(10, 1), None, None, "PACKET_EXPIRED"),
    (_at(8, 59), None, None, "PACKET_NOT_YET_VALID"),
    (_at(9, 30), "refs_expire_at", "2026-10-25T09:15:00Z", "REFERENCES_EXPIRED"),
])
def test_packet_and_references_must_be_current(context, monkeypatch, now, field, value, code):
    packet, ledger, broker = context
    _clock(monkeypatch, now)
    if field:
        packet["recovery"][field] = value
    with pytest.raises(preflight.PreflightError) as error:
        broker.prebind_and_reserve(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000)
    assert error.value.code == code
    assert not ledger._reservations and not ledger._intents


def test_caller_timestamp_cannot_bypass_server_clock(context, monkeypatch):
    packet, ledger, broker = context
    _clock(monkeypatch, _at(10, 1))
    with pytest.raises(preflight.PreflightError):
        broker.prebind_and_reserve(call_id=str(uuid.uuid4()), packet=packet,
                                   reserved_micros=1000, now_iso="2026-10-25T09:30:00Z")
    assert not ledger._reservations


def test_lease_expiring_after_reservation_prevents_dispatch(context, monkeypatch):
    packet, ledger, broker = context
    _clock(monkeypatch, _at(9, 29, 59), _at(9, 30, 1))
    broker.leases[(packet["run_id"], packet["task_id"])].expires_at = "2026-10-25T09:30:00Z"
    sent = []
    with pytest.raises(preflight.PreflightError) as error:
        broker.dispatch_bound_call(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000,
                                   transport=lambda *_: sent.append(True))
    assert error.value.code == "LEASE_EXPIRED"
    assert sent == [] and broker.provider_calls_attempted == 0
    assert all(r.status == "RESERVED" for r in ledger._reservations.values())


def test_current_packet_and_lease_are_accepted(context, monkeypatch):
    packet, ledger, broker = context
    _clock(monkeypatch, _at(9, 30))
    binding = broker.prebind_and_reserve(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000)
    assert ledger._reservations[(packet["tenant_id"], packet["project_id"], binding.call_id)].status == "RESERVED"


def test_agent_change_after_reservation_prevents_dispatch(context, monkeypatch):
    packet, ledger, broker = context
    _clock(monkeypatch, _at(9, 30))
    original = broker.prebind_and_reserve

    def change_agent(**kwargs):
        binding = original(**kwargs)
        broker.leases[(packet["run_id"], packet["task_id"])].agent_id = "different-agent"
        return binding

    monkeypatch.setattr(broker, "prebind_and_reserve", change_agent)
    sent = []
    with pytest.raises(preflight.PreflightError) as error:
        broker.dispatch_bound_call(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000,
                                   transport=lambda *_: sent.append(True))
    assert error.value.code == "STALE_LEASE"
    assert sent == [] and broker.provider_calls_attempted == 0
    assert all(r.status == "RESERVED" for r in ledger._reservations.values())


@pytest.mark.parametrize("expiry", ["2026-10-25T10:00:00z", "2026-10-25T12:00:00+02:00"])
def test_lowercase_utc_suffix_and_offset_are_compared_as_instants(context, monkeypatch, expiry):
    packet, _, broker = context
    _clock(monkeypatch, _at(9, 30))
    broker.leases[(packet["run_id"], packet["task_id"])].expires_at = expiry
    broker.prebind_and_reserve(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000)


def test_references_expiring_after_reservation_prevent_dispatch(context, monkeypatch):
    packet, ledger, broker = context
    packet["recovery"]["refs_expire_at"] = "2026-10-25T09:30:00Z"
    _clock(monkeypatch, _at(9, 29, 59), _at(9, 30, 1))
    sent = []
    with pytest.raises(preflight.PreflightError) as error:
        broker.dispatch_bound_call(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000,
                                   transport=lambda *_: sent.append(True))
    assert error.value.code == "REFERENCES_EXPIRED"
    assert sent == [] and broker.provider_calls_attempted == 0
    assert all(r.status == "RESERVED" for r in ledger._reservations.values())


def test_invalid_lease_timestamp_fails_closed(context, monkeypatch):
    packet, ledger, broker = context
    _clock(monkeypatch, _at(9, 30))
    broker.leases[(packet["run_id"], packet["task_id"])].expires_at = "tomorrow"
    with pytest.raises(preflight.PreflightError) as error:
        broker.prebind_and_reserve(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000)
    assert error.value.code == "LEASE_TIME_INVALID"
    assert not ledger._reservations


def test_canonical_semantic_parser_failure_is_a_preflight_rejection(context, monkeypatch):
    packet, ledger, broker = context
    _clock(monkeypatch, _at(9, 30))
    packet["issued_at"] = packet["issued_at"].replace("Z", "z")
    with pytest.raises(preflight.PreflightError) as error:
        broker.prebind_and_reserve(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000)
    assert error.value.code == "PACKET_SEMANTIC_INVALID"
    assert not ledger._reservations


@pytest.mark.parametrize("change,code", [
    ("packet", "PACKET_BINDING_MISMATCH"),
    ("consent", "PROVIDER_CONSENT_MISSING"),
    ("allowlist", "PROVIDER_NOT_ALLOWED"),
])
def test_dispatch_rechecks_packet_and_provider_authorization(context, monkeypatch, change, code):
    packet, ledger, broker = context
    _clock(monkeypatch, _at(9, 30))
    original = broker.prebind_and_reserve

    def change_after_reservation(**kwargs):
        binding = original(**kwargs)
        if change == "packet":
            packet["cache_plan"]["model"] = "another-model"
        elif change == "consent":
            broker.set_provider_consent(packet["tenant_id"], packet["cache_plan"]["provider"], consented=False)
        else:
            broker.allowed_providers.remove(packet["cache_plan"]["provider"])
        return binding

    monkeypatch.setattr(broker, "prebind_and_reserve", change_after_reservation)
    sent = []
    with pytest.raises(preflight.PreflightError) as error:
        broker.dispatch_bound_call(call_id=str(uuid.uuid4()), packet=packet, reserved_micros=1000,
                                   transport=lambda *_: sent.append(True))
    assert error.value.code == code
    assert not sent and broker.provider_calls_attempted == 0
    assert all(r.status == "RESERVED" for r in ledger._reservations.values())
