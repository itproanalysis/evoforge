"""Synthetic receipts for contract/isolated-DB checks; no provider billing evidence."""
from datetime import datetime, timezone
from uuid import uuid4


def receipt_document(*, tenant=None, project=None, packet=None, call=None):
    call = call or uuid4()
    return {
        "schema_version": "provider-usage-receipt/v1",
        "receipt_id": str(uuid4()),
        "tenant_id": str(tenant or uuid4()),
        "project_id": str(project or uuid4()),
        "packet_id": str(packet or uuid4()),
        "call_id": str(call),
        "reservation_key": str(call),
        "call_purpose": "task_turn",
        "provider": "meta",
        "model": "muse-spark-1.3",
        "provider_request_id": "synthetic-test-" + uuid4().hex,
        "source": "provider_billed",
        "billing_owner": "platform",
        "tokens": {"uncached_input": 11, "cache_write": 0, "cache_read": 3, "output": 7,
                   "reasoning_output": 2},
        "raw_usage_fields": {"prompt_tokens": 14, "completion_tokens": 7,
                             "prompt_tokens_details": {"cached_tokens": 3}},
        "cost_micros": 80,
        "customer_price_micros": 110,
        "currency": "USD",
        "price_table_version": "synthetic-test-v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
