"""Canonical receipt documents validated against the immutable v1 contract.

Inputs belong to the trusted Broker/reconciler, not model-generated JSON. Schema
validation and a digest do not verify a provider invoice or its billed amount.
The ledger entry link is derived at read time and is not a caller-owned field.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker


class ReceiptInvalid(ValueError):
    pass


@lru_cache(maxsize=1)
def _validator():
    path = Path(__file__).resolve().parents[3] / "docs/evoforge-v4.2/contracts/schemas/provider-usage-receipt.v1.schema.json"
    # Explicit selection fails closed if the required RFC3339 dependency is
    # missing; a default FormatChecker silently omits unavailable checks.
    checker = FormatChecker(formats=["date-time"])
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")), format_checker=checker)


def canonical_receipt(document: dict) -> tuple[dict, str]:
    """Return an independent validated document and SHA-256; never echo data in errors."""
    try:
        error = next(_validator().iter_errors(document), None)
    except (TypeError, ValueError):
        raise ReceiptInvalid("invalid receipt document") from None
    if error is not None:
        location = "/".join(str(p) for p in error.absolute_path) or "<root>"
        raise ReceiptInvalid(f"invalid receipt field: {location}")
    for key in ("receipt_id", "tenant_id", "project_id", "packet_id", "call_id"):
        try:
            canonical_id = str(UUID(document[key]))
        except ValueError:
            raise ReceiptInvalid(f"invalid receipt UUID: {key}") from None
        if canonical_id != document[key]:
            raise ReceiptInvalid(f"invalid receipt UUID: {key}")
    if document["recorded_at"] != document["recorded_at"].strip():
        raise ReceiptInvalid("invalid receipt field: recorded_at")
    for key in ("cost_micros", "customer_price_micros"):
        value = document[key]
        if type(value) is not int or not 0 <= value <= 2**63 - 1:
            raise ReceiptInvalid(f"{key} must be a non-negative int64")
    for key, value in document["tokens"].items():
        if key != "cache_write_ttl" and (type(value) is not int or not 0 <= value <= 2**63 - 1):
            raise ReceiptInvalid(f"token counter {key} must be a non-negative int64")
    if document["reservation_key"] != document["call_id"]:
        raise ReceiptInvalid("reservation key must be the reserved call UUID")
    if document.get("ledger_entry_id") is not None:
        raise ReceiptInvalid("ledger entry linkage is server-owned")
    normalized = {k: v for k, v in document.items() if k != "ledger_entry_id"}
    try:
        encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        copied = json.loads(encoded)
        if copied != normalized:
            raise ReceiptInvalid("receipt must contain JSON types")
        return copied, hashlib.sha256(encoded).hexdigest()
    except (TypeError, ValueError, UnicodeError):
        raise ReceiptInvalid("receipt must contain canonical JSON data") from None
