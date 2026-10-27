"""Receipt-bound access to the immutable PostgreSQL Trust Kernel.

Scope comes from trusted server authentication/configuration, never model output.
Amounts are integer micro-USD. Each operation owns its transaction and connection;
RLS context cannot escape to a subsequent request. This module never calls a model.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
import re
from uuid import UUID

class KernelRejected(ValueError):
    pass


class KernelNotFound(KernelRejected):
    pass


class BudgetRefused(KernelRejected):
    pass


class KernelUnavailable(RuntimeError):
    pass


def _amount(value: int, name: str) -> int:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ValueError(f"{name} must be a positive int64 amount")
    return value


def cents_to_micros(cents: int) -> int:
    return _amount(_amount(cents, "cents") * 10_000, "micros")


@dataclass(frozen=True)
class KernelScope:
    tenant_id: UUID
    project_id: UUID

    def __post_init__(self):
        object.__setattr__(self, "tenant_id", UUID(str(self.tenant_id)))
        object.__setattr__(self, "project_id", UUID(str(self.project_id)))


@dataclass(frozen=True)
class ReservationState:
    call_id: UUID
    period_start: date
    reserved_micros: int
    actual_micros: int | None
    status: str
    outcome: str


class PostgresKernel:
    def __init__(self, dsn: str, scope: KernelScope):
        if not dsn or not isinstance(scope, KernelScope):
            raise ValueError("database connection and trusted scope required")
        self._dsn = dsn
        self.scope = scope

    @contextmanager
    def _transaction(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise KernelUnavailable("PostgreSQL client unavailable") from None
        try:
            with psycopg.connect(self._dsn, autocommit=True, connect_timeout=5, row_factory=dict_row) as conn:
                with conn.transaction():
                    conn.execute("SET LOCAL ROLE core_app")
                    conn.execute("SELECT set_config('app.tenant_id', %s, true), "
                                 "set_config('app.project_ids', %s, true)",
                                 (str(self.scope.tenant_id), str(self.scope.project_id)))
                    yield conn
        except psycopg.errors.CheckViolation as error:
            if (error.diag.message_primary or "").startswith(("BUDGET_", "CREDIT_EXHAUSTED")):
                raise BudgetRefused("project budget or prepaid credit refused reservation") from None
            raise KernelRejected("Trust Kernel rejected the operation") from None
        except psycopg.errors.NoDataFound:
            raise KernelNotFound("resource not found in scope") from None
        except (psycopg.IntegrityError, psycopg.errors.RaiseException,
                psycopg.errors.InsufficientPrivilege):
            raise KernelRejected("Trust Kernel rejected the operation") from None
        except psycopg.Error:
            # Connection errors can contain credentials/host details. Do not
            # propagate a raw DSN or provider data into API responses or logs.
            raise KernelUnavailable("PostgreSQL Trust Kernel unavailable") from None

    def _intent_key(self, call_id: UUID) -> str:
        return f"{self.scope.project_id}:{call_id}"

    def _read(self, conn, call_id: UUID, *, lock: bool = False) -> ReservationState:
        if lock:
            # Acquire the reservation lock before reading its joined intent.
            # A joined SELECT ... FOR UPDATE may wait, then see the new r row
            # with an intent from its older READ COMMITTED statement snapshot.
            locked = conn.execute("SELECT 1 FROM core.cost_reservations WHERE tenant_id=%s "
                                  "AND project_id=%s AND request_key=%s FOR UPDATE",
                                  (self.scope.tenant_id, self.scope.project_id, str(call_id))).fetchone()
            if not locked:
                raise KernelNotFound("reservation or provider intent not found in scope")
        query = """SELECT r.period_start, r.reserved_micros, r.actual_micros, r.status,
                          i.status AS outcome
                     FROM core.cost_reservations r
                     LEFT JOIN core.side_effect_intents i ON i.tenant_id=r.tenant_id
                       AND i.kind='provider.call' AND i.idempotency_key=%s
                    WHERE r.tenant_id=%s AND r.project_id=%s AND r.request_key=%s"""
        row = conn.execute(query,
                           (self._intent_key(call_id), self.scope.tenant_id,
                            self.scope.project_id, str(call_id))).fetchone()
        if not row or row["outcome"] is None:
            raise KernelNotFound("reservation or provider intent not found in scope")
        return ReservationState(call_id=call_id, **row)

    def reservation(self, call_id: UUID) -> ReservationState:
        call_id = UUID(str(call_id))
        with self._transaction() as conn:
            return self._read(conn, call_id)

    def reserve_cost(self, call_id: UUID, period: date, amount_micros: int) -> ReservationState:
        call_id = UUID(str(call_id))
        _amount(amount_micros, "amount_micros")
        if type(period) is not date:
            raise ValueError("period must be a date")
        with self._transaction() as conn:
            return self._reserve(conn, call_id, period, amount_micros)

    def _reserve(self, conn, call_id: UUID, period: date, amount_micros: int) -> ReservationState:
        # Same lock as core.reserve_cost, acquired before its idempotency
        # lookup so concurrent retries of one call also remain idempotent.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                     (f"core.credit:{self.scope.tenant_id}",))
        exists = conn.execute("SELECT 1 FROM core.cost_reservations WHERE tenant_id=%s "
                              "AND project_id=%s AND request_key=%s",
                              (self.scope.tenant_id, self.scope.project_id, str(call_id))).fetchone()
        if exists:
            previous = self._read(conn, call_id, lock=True)
            if previous.period_start != period or previous.reserved_micros != amount_micros:
                raise KernelRejected("call id reused with different reservation parameters")
            return previous
        conn.execute("SELECT core.reserve_cost(%s,%s,%s,%s,%s)",
                     (self.scope.tenant_id, self.scope.project_id, period, str(call_id), amount_micros))
        conn.execute("INSERT INTO core.side_effect_intents (tenant_id,kind,idempotency_key) "
                     "VALUES (%s,'provider.call',%s)", (self.scope.tenant_id, self._intent_key(call_id)))
        return self._read(conn, call_id)

    def mark_sent(self, call_id: UUID, expected_builder_model: str = "muse-spark-1.3") -> ReservationState:
        call_id = UUID(str(call_id))
        with self._transaction() as conn:
            previous = self._read(conn, call_id, lock=True)
            if previous.status != "RESERVED" or previous.outcome != "RESERVED":
                raise KernelRejected("provider call already sent or reservation closed")
            from evoforge.postgres_builder import validate_dispatch
            validate_dispatch(conn, self.scope, call_id, expected_builder_model)
            conn.execute("UPDATE core.side_effect_intents SET status='SENT' WHERE tenant_id=%s "
                         "AND kind='provider.call' AND idempotency_key=%s",
                         (self.scope.tenant_id, self._intent_key(call_id)))
            return self._read(conn, call_id)

    def mark_unknown(self, call_id: UUID) -> ReservationState:
        call_id = UUID(str(call_id))
        with self._transaction() as conn:
            previous = self._read(conn, call_id, lock=True)
            if previous.status != "RESERVED" or previous.outcome != "SENT":
                raise KernelRejected("only an in-flight call can have an unknown outcome")
            conn.execute("UPDATE core.side_effect_intents SET status='UNKNOWN_EXTERNAL_OUTCOME' "
                         "WHERE tenant_id=%s AND kind='provider.call' AND idempotency_key=%s",
                         (self.scope.tenant_id, self._intent_key(call_id)))
            return self._read(conn, call_id)

    def release_not_accepted(self, call_id: UUID) -> ReservationState:
        call_id = UUID(str(call_id))
        with self._transaction() as conn:
            previous = self._read(conn, call_id, lock=True)
            if previous.status == "RELEASED":
                return previous
            if previous.status != "RESERVED" or previous.outcome not in {"RESERVED", "SENT"}:
                raise KernelRejected("unknown or confirmed calls require receipt reconciliation")
            if previous.outcome == "SENT":
                conn.execute("UPDATE core.side_effect_intents SET status='FAILED' WHERE tenant_id=%s "
                             "AND kind='provider.call' AND idempotency_key=%s",
                             (self.scope.tenant_id, self._intent_key(call_id)))
            conn.execute("UPDATE core.cost_reservations SET status='RELEASED' WHERE tenant_id=%s "
                         "AND project_id=%s AND request_key=%s",
                         (self.scope.tenant_id, self.scope.project_id, str(call_id)))
            return self._read(conn, call_id)

    def settle_reservation(self, call_id: UUID, receipt_id: UUID, customer_micros: int) -> ReservationState:
        call_id, receipt_id = UUID(str(call_id)), UUID(str(receipt_id))
        _amount(customer_micros, "customer_micros")
        with self._transaction() as conn:
            previous = self._read(conn, call_id, lock=True)
            if previous.status == "COMMITTED":
                charged = conn.execute("SELECT receipt_id, -customer_micros AS amount FROM core.usage_ledger "
                                       "WHERE tenant_id=%s AND project_id=%s AND idempotency_key=%s",
                                       (self.scope.tenant_id, self.scope.project_id, f"settle:{call_id}")).fetchone()
                if charged and charged["receipt_id"] == receipt_id and charged["amount"] == customer_micros:
                    return previous
                raise KernelRejected("settlement replay differs from committed receipt")
            if previous.status != "RESERVED" or previous.outcome not in {"SENT", "UNKNOWN_EXTERNAL_OUTCOME"}:
                raise KernelRejected("reservation is not an in-flight provider call")
            from evoforge.postgres_builder import binding, check_document
            bound = binding(conn, self.scope, call_id)
            conn.execute("SET LOCAL ROLE ctx_gateway")
            receipt = conn.execute("SELECT cost_micros, price_table_version, provider_request_id "
                                   "FROM ctx.provider_usage_receipts WHERE tenant_id=%s AND project_id=%s "
                                   "AND receipt_id=%s AND call_id=%s AND billing_owner='platform'",
                                   (self.scope.tenant_id, self.scope.project_id, receipt_id, call_id)).fetchone()
            if not receipt or not receipt["provider_request_id"]:
                raise KernelRejected("matching platform receipt with provider reference required")
            quoted = conn.execute("SELECT document,document_sha256 FROM runtime.provider_receipt_documents "
                                  "WHERE tenant_id=%s AND project_id=%s AND receipt_id=%s",
                                  (self.scope.tenant_id, self.scope.project_id, receipt_id)).fetchone()
            if quoted:
                from evoforge.postgres_receipts import canonical_receipt
                document, digest = canonical_receipt(quoted["document"])
                if (digest != quoted["document_sha256"]
                        or document["customer_price_micros"] != customer_micros):
                    raise KernelRejected("settlement amount differs from stored customer quote")
                check_document(bound, document)
            elif bound:
                raise KernelRejected("bound Builder call requires a canonical receipt document")
            conn.execute("SET LOCAL ROLE core_app")
            conn.execute("SELECT core.settle_reservation(%s,%s,%s,%s,%s,%s,%s)",
                         (self.scope.tenant_id, self.scope.project_id, str(call_id), customer_micros,
                          receipt["cost_micros"], receipt_id, receipt["price_table_version"]))
            conn.execute("UPDATE core.side_effect_intents SET status='CONFIRMED', external_ref=%s "
                         "WHERE tenant_id=%s AND kind='provider.call' AND idempotency_key=%s",
                         (receipt["provider_request_id"], self.scope.tenant_id, self._intent_key(call_id)))
            return self._read(conn, call_id)

    def authorize_merge(self, candidate_id: UUID, head_sha: str, policy_hash: str) -> None:
        candidate_id = UUID(str(candidate_id))
        if not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", head_sha) or not re.fullmatch(r"[a-f0-9]{64}", policy_hash):
            raise ValueError("immutable head SHA and policy hash required")
        with self._transaction() as conn:
            conn.execute("SELECT core.authorize_merge(%s,%s,%s,%s,%s)",
                         (self.scope.tenant_id, self.scope.project_id, candidate_id, head_sha, policy_hash))

    def record_receipt(self, document: dict) -> dict:
        """Atomically store a canonical Broker/reconciler receipt and its ctx row."""
        from evoforge.postgres_receipts import canonical_receipt

        record, digest = canonical_receipt(document)
        if (record["tenant_id"] != str(self.scope.tenant_id)
                or record["project_id"] != str(self.scope.project_id)):
            raise KernelRejected("receipt scope mismatch")
        call_id, receipt_id = UUID(record["call_id"]), UUID(record["receipt_id"])
        with self._transaction() as conn:
            from psycopg.types.json import Json, Jsonb
            state = self._read(conn, call_id, lock=True)
            from evoforge.postgres_builder import binding, check_document
            check_document(binding(conn, self.scope, call_id), record)
            reserved_at = conn.execute("SELECT created_at FROM core.cost_reservations WHERE tenant_id=%s "
                                       "AND project_id=%s AND request_key=%s",
                                       (self.scope.tenant_id, self.scope.project_id, str(call_id))).fetchone()["created_at"]
            conn.execute("SET LOCAL ROLE ctx_gateway")
            existing = conn.execute("SELECT document_sha256 FROM runtime.provider_receipt_documents "
                                    "WHERE tenant_id=%s AND project_id=%s AND receipt_id=%s",
                                    (self.scope.tenant_id, self.scope.project_id, receipt_id)).fetchone()
            if existing:
                if existing["document_sha256"] != digest:
                    raise KernelRejected("receipt replay differs from stored document")
                conn.execute("SET LOCAL ROLE core_app")
                ledger = conn.execute("SELECT entry_id FROM core.usage_ledger WHERE tenant_id=%s AND project_id=%s "
                                      "AND receipt_id=%s AND entry_kind='model_usage'",
                                      (self.scope.tenant_id, self.scope.project_id, receipt_id)).fetchone()
                return {**record, "ledger_entry_id": str(ledger["entry_id"]) if ledger else None}
            if state.status != "RESERVED" or state.outcome not in {"SENT", "UNKNOWN_EXTERNAL_OUTCOME"}:
                raise KernelRejected("receipt requires an in-flight reserved call")
            packet = conn.execute("SELECT provider,model,issued_at,expires_at FROM ctx.context_packets "
                                  "WHERE tenant_id=%s AND project_id=%s AND packet_id=%s",
                                  (self.scope.tenant_id, self.scope.project_id, UUID(record["packet_id"]))).fetchone()
            if (not packet or packet["provider"] != record["provider"] or packet["model"] != record["model"]
                    or not packet["issued_at"] <= reserved_at < packet["expires_at"]):
                raise KernelRejected("receipt packet was not a matching context at reservation time")
            tokens = record["tokens"]
            conn.execute("""INSERT INTO ctx.provider_usage_receipts
                (tenant_id,project_id,receipt_id,packet_id,call_id,call_purpose,provider,model,
                 provider_request_id,source,billing_owner,uncached_input,cache_write,cache_write_ttl,
                 cache_read,output_tokens,raw_usage_fields,cost_micros,currency,price_table_version,recorded_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'platform',%s,%s,%s,%s,%s,%s,%s,'USD',%s,%s)""",
                (self.scope.tenant_id, self.scope.project_id, receipt_id, UUID(record["packet_id"]), call_id,
                 record["call_purpose"], record["provider"], record["model"], record.get("provider_request_id"),
                 record["source"], tokens["uncached_input"], tokens["cache_write"], tokens.get("cache_write_ttl"),
                 tokens["cache_read"], tokens["output"],
                 Jsonb(record["raw_usage_fields"]) if "raw_usage_fields" in record else None,
                 record["cost_micros"], record["price_table_version"], record["recorded_at"]))
            conn.execute("INSERT INTO runtime.provider_receipt_documents "
                         "(tenant_id,project_id,receipt_id,call_id,document,document_sha256) VALUES (%s,%s,%s,%s,%s,%s)",
                         (self.scope.tenant_id, self.scope.project_id, receipt_id, call_id, Json(record), digest))
            return {**record, "ledger_entry_id": None}

    def receipt_document(self, receipt_id: UUID) -> dict:
        from evoforge.postgres_receipts import canonical_receipt
        receipt_id = UUID(str(receipt_id))
        with self._transaction() as conn:
            ledger = conn.execute("SELECT entry_id FROM core.usage_ledger WHERE tenant_id=%s AND project_id=%s "
                                  "AND receipt_id=%s AND entry_kind='model_usage'",
                                  (self.scope.tenant_id, self.scope.project_id, receipt_id)).fetchone()
            conn.execute("SET LOCAL ROLE ctx_gateway")
            row = conn.execute("SELECT document,document_sha256 FROM runtime.provider_receipt_documents "
                               "WHERE tenant_id=%s AND project_id=%s AND receipt_id=%s",
                               (self.scope.tenant_id, self.scope.project_id, receipt_id)).fetchone()
            if not row:
                raise KernelNotFound("receipt not found in scope")
            record, digest = canonical_receipt(row["document"])
            if digest != row["document_sha256"]:
                raise KernelRejected("receipt digest mismatch")
            return {**record, "ledger_entry_id": str(ledger["entry_id"]) if ledger else None}

    def settle_from_receipt(self, receipt_id: UUID) -> ReservationState:
        """Use the stored customer quote; no caller-supplied replacement amount."""
        record = self.receipt_document(receipt_id)
        return self.settle_reservation(UUID(record["call_id"]), UUID(record["receipt_id"]),
                                       record["customer_price_micros"])

    def prepare_builder_call(self, call_id, period, amount_micros, packet_id, price_table_version,
                             expected_model="muse-spark-1.3"):
        from evoforge.postgres_builder import prepare
        return prepare(self, call_id, period, amount_micros, packet_id, price_table_version, expected_model)

    def builder_call(self, call_id):
        from evoforge.postgres_builder import read
        return read(self, call_id)
