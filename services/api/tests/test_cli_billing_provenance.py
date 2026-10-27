"""Do not convert unknown CLI billing or malformed usage into a settled receipt."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[1]
_ROOT = _API.parents[1]
sys.path.insert(0, str(_API))

from evoforge.eval_runner_and_preflight import (  # noqa: E402
    DevBuilderCLIGuard,
    PreflightCallBroker,
    PreflightError,
)
from evoforge.reconciler_policy import ReconcilerLedger  # noqa: E402


@pytest.fixture
def setup_call():
    packet = json.loads(
        (_ROOT / "docs/evoforge-v4.2/contracts/examples/valid/context-packet.builder.json")
        .read_text(encoding="utf-8")
    )
    tenant, project = packet["tenant_id"], packet["project_id"]
    period = "2026-10-01"
    ledger = ReconcilerLedger()
    ledger.set_project_budget(tenant, project, period, 100_000)
    ledger.grant_credit(tenant, 200_000, idempotency_key="synthetic-credit")
    broker = PreflightCallBroker(ledger=ledger)
    broker.set_provider_consent(tenant, packet["cache_plan"]["provider"], consented=True)
    broker.register_lease(packet["run_id"], packet["task_id"], packet["recipient"]["agent_id"],
                          lease_epoch=packet["fencing"]["lease_epoch"], active=True)
    return packet, ledger, DevBuilderCLIGuard(broker), period


_USAGE = {"provider_request_id": "synthetic-request", "uncached_input_tokens": 17,
          "cached_read_tokens": 0, "cache_write_tokens": 0, "output_tokens": 9}


@pytest.mark.parametrize(
    ("extra", "caller_amount"),
    [({}, None), ({}, 12_000), ({"cost_micros": 200}, None),
     ({"customer_price_micros": 500}, None),
     ({"cost_micros": True, "customer_price_micros": 500}, None),
     ({"cost_micros": 2.5, "customer_price_micros": 500}, None),
     ({"cost_micros": "200", "customer_price_micros": 500}, None),
     ({"cost_micros": -1, "customer_price_micros": 500}, None),
     ({"cost_micros": 200, "customer_price_micros": False}, None),
     ({"cost_micros": 200, "customer_price_micros": -1}, None),
     ({"cost_micros": 200, "customer_price_micros": 500}, 900)],
)
def test_unverified_cost_retains_hold_and_creates_no_receipt(setup_call, extra, caller_amount):
    packet, ledger, guard, period = setup_call
    call_id = str(uuid.uuid4())
    with pytest.raises(PreflightError, match="CLI"):
        guard.run_cli_task(task_spec={"id": "synthetic"}, packet=packet,
                           reserved_micros=20_000, cli_runner=lambda _: {**_USAGE, **extra},
                           actual_micros=caller_amount, call_id=call_id, period_start=period)
    reservation = ledger._reservations[(packet["tenant_id"], packet["project_id"], call_id)]
    intent_id = ledger._intents_by_key[(packet["tenant_id"], "provider.call", call_id)]
    assert reservation.status == "RESERVED" and reservation.actual_micros is None
    assert ledger._intents[(packet["tenant_id"], intent_id)].status == "UNKNOWN_EXTERNAL_OUTCOME"
    assert not ledger._receipts
    assert all(row.entry_kind != "model_usage" and row.receipt_id is None for row in ledger._ledger)


@pytest.mark.parametrize("field,bad_value", [
    ("uncached_input_tokens", True), ("uncached_input_tokens", 1.5),
    ("uncached_input_tokens", "17"), ("uncached_input_tokens", -1),
    ("cached_read_tokens", None), ("cache_write_tokens", None), ("output_tokens", False),
])
def test_malformed_usage_is_not_coerced_into_a_receipt(setup_call, field, bad_value):
    packet, ledger, guard, period = setup_call
    call_id = str(uuid.uuid4())
    output = {**_USAGE, field: bad_value, "cost_micros": 200, "customer_price_micros": 500}
    with pytest.raises(PreflightError, match="CLI"):
        guard.run_cli_task(task_spec={"id": "synthetic"}, packet=packet,
                           reserved_micros=20_000, cli_runner=lambda _: output,
                           call_id=call_id, period_start=period)
    assert ledger._reservations[(packet["tenant_id"], packet["project_id"], call_id)].status == "RESERVED"
    assert not ledger._receipts


@pytest.mark.parametrize(("provider_cost", "customer_price"), [(200, 500), (0, 0)])
def test_explicit_amounts_settle_with_distinct_provider_and_customer_values(setup_call, provider_cost, customer_price):
    packet, ledger, guard, period = setup_call
    call_id = str(uuid.uuid4())
    output = {**_USAGE, "cost_micros": provider_cost, "customer_price_micros": customer_price}
    result = guard.run_cli_task(task_spec={"id": "synthetic"}, packet=packet,
                                reserved_micros=20_000, cli_runner=lambda _: output,
                                call_id=call_id, period_start=period)
    assert result["receipt"]["cost_micros"] == provider_cost
    assert result["receipt"]["customer_price_micros"] == customer_price
    assert result["settlement"]["settlement"]["actual_micros"] == customer_price
    assert ledger._reservations[(packet["tenant_id"], packet["project_id"], call_id)].status == "COMMITTED"
