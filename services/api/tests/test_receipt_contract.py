"""Receipt shape and canonical JSON are independent from invoice verification."""
from copy import deepcopy
from pathlib import Path
import sys
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evoforge.postgres_receipts import ReceiptInvalid, canonical_receipt  # noqa: E402
from receipt_fixtures import receipt_document  # noqa: E402


def test_canonical_document_is_independent_and_key_order_does_not_change_digest():
    document = receipt_document()
    record, digest = canonical_receipt(document)
    reordered = dict(reversed(list(document.items())))
    reordered["tokens"] = dict(reversed(list(document["tokens"].items())))
    assert canonical_receipt(reordered) == (record, digest)
    assert len(digest) == 64 and record == document
    document["tokens"]["output"] = 999
    document["raw_usage_fields"]["prompt_tokens_details"]["cached_tokens"] = 999
    assert record["tokens"]["output"] == 7
    assert record["raw_usage_fields"]["prompt_tokens_details"]["cached_tokens"] == 3


@pytest.mark.parametrize("field", ["cost_micros", "customer_price_micros"])
@pytest.mark.parametrize("value", [True, 1.0, "1", -1, 2**63])
def test_money_rejects_coercion_and_int64_overflow(field, value):
    document = receipt_document()
    document[field] = value
    with pytest.raises(ReceiptInvalid):
        canonical_receipt(document)


@pytest.mark.parametrize("field", ["uncached_input", "cache_write", "cache_read", "output", "reasoning_output"])
@pytest.mark.parametrize("value", [False, 1.0, -1, 2**63])
def test_token_counters_are_nonnegative_int64(field, value):
    document = receipt_document()
    document["tokens"][field] = value
    with pytest.raises(ReceiptInvalid):
        canonical_receipt(document)


@pytest.mark.parametrize("field,value", [
    ("schema_version", "provider-usage-receipt/v0"),
    ("tenant_id", "not-a-uuid"), ("receipt_id", str(uuid4()).upper()),
    ("currency", "KRW"), ("billing_owner", "byok_customer"),
    ("source", "verified"), ("provider", "automatic-fallback"),
    ("call_purpose", "unknown"), ("model", ""), ("price_table_version", ""),
    ("recorded_at", "2026-10-27"), ("recorded_at", "2026-13-27T00:00:00Z"),
    ("recorded_at", "2026-10-27T00:00:00Z\n"),
    ("provider_request_id", ""), ("reservation_key", str(uuid4())),
    ("ledger_entry_id", str(uuid4())), ("unexpected", "must-not-leak"),
])
def test_contract_scope_vocabulary_and_server_owned_linkage(field, value):
    document = receipt_document()
    document[field] = value
    with pytest.raises(ReceiptInvalid) as exc:
        canonical_receipt(document)
    assert "must-not-leak" not in str(exc.value)


@pytest.mark.parametrize("field", ["provider_request_id", "raw_usage_fields", "reservation_key", "tokens"])
def test_required_provider_billing_evidence_cannot_be_dropped(field):
    document = receipt_document()
    del document[field]
    with pytest.raises(ReceiptInvalid):
        canonical_receipt(document)


def test_estimated_usage_is_not_promoted_to_provider_billed():
    document = receipt_document()
    document["source"] = "estimated"
    document.pop("provider_request_id")
    document.pop("raw_usage_fields")
    record, _ = canonical_receipt(document)
    assert record["source"] == "estimated" and "provider_request_id" not in record


def test_zero_price_is_valid_receipt_even_though_kernel_zero_charge_policy_is_pending():
    document = receipt_document()
    document.update(cost_micros=0, customer_price_micros=0, ledger_entry_id=None)
    record, digest = canonical_receipt(document)
    assert record["cost_micros"] == record["customer_price_micros"] == 0
    assert "ledger_entry_id" not in record
    assert canonical_receipt(record)[1] == digest


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object()])
def test_raw_usage_still_has_to_be_json(value):
    document = receipt_document()
    document["raw_usage_fields"]["bad"] = value
    with pytest.raises(ReceiptInvalid):
        canonical_receipt(document)


@pytest.mark.parametrize("value", [None, [], "must-not-leak"])
def test_non_document_is_rejected_safely(value):
    with pytest.raises(ReceiptInvalid) as exc:
        canonical_receipt(value)
    assert "must-not-leak" not in str(exc.value)


def test_raw_usage_changes_cannot_reuse_a_document_digest():
    document = receipt_document()
    other = deepcopy(document)
    other["raw_usage_fields"]["completion_tokens"] += 1
    assert canonical_receipt(document)[1] != canonical_receipt(other)[1]


@pytest.mark.parametrize("field", ["receipt_id", "tenant_id", "project_id", "packet_id", "call_id"])
def test_uuid_pattern_end_anchor_cannot_accept_a_trailing_newline(field):
    document = receipt_document()
    document[field] += "\n"
    if field == "call_id":
        document["reservation_key"] = document[field]
    with pytest.raises(ReceiptInvalid):
        canonical_receipt(document)


def test_raw_object_keys_cannot_silently_change_type():
    document = receipt_document()
    document["raw_usage_fields"] = {1: "not-a-JSON-object-key"}
    with pytest.raises(ReceiptInvalid):
        canonical_receipt(document)
