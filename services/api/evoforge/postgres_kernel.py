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


class _ConnectionPool:
    """Bounded, thread-safe reuse of autocommit connections (production: EVO_PG_POOL_SIZE).

    Opening a connection per transaction exhausted the small Cloud SQL instance's slots under load ("remaining
    connection slots are reserved"), which stalled every endpoint. Each process now holds at most `size`
    connections (up to 2x only for a transaction nested inside one this thread already holds, so it cannot wait on
    itself); a caller waits up to `wait_s` for a free one instead of opening more.
    """

    def __init__(self, dsn: str, size: int, wait_s: float, idle_check_s: float = 30.0):
        import threading
        self.dsn, self.size, self.wait_s, self.idle_check_s = dsn, size, wait_s, idle_check_s
        self._idle: list = []  # [(conn, released_at)]
        self._open = 0
        self._cond = threading.Condition()
        self._held = threading.local()  # connections this thread holds: a nested transaction must not wait on itself

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, autocommit=True, connect_timeout=5, row_factory=dict_row)

    def acquire(self):
        import time as _time
        deadline = _time.monotonic() + self.wait_s
        with self._cond:
            while True:
                while self._idle:
                    conn, released = self._idle.pop()
                    if conn.closed:
                        self._open -= 1
                        continue
                    if _time.monotonic() - released > self.idle_check_s:
                        try:  # a long-idle connection may have been dropped by the server
                            conn.execute("SELECT 1")
                        except Exception:
                            self._discard(conn)
                            continue
                    self._held.n = getattr(self._held, "n", 0) + 1
                    return conn
                nested = getattr(self._held, "n", 0) > 0
                if self._open < self.size or (nested and self._open < 2 * self.size):
                    self._open += 1
                    break
                left = deadline - _time.monotonic()
                if left <= 0:
                    raise KernelUnavailable("PostgreSQL Trust Kernel busy")
                self._cond.wait(left)
        try:
            conn = self._connect()
        except Exception:
            with self._cond:
                self._open -= 1
                self._cond.notify()
            raise
        self._held.n = getattr(self._held, "n", 0) + 1
        return conn

    def _discard(self, conn):
        try:
            conn.close()
        except Exception:
            pass
        self._open -= 1

    def release(self, conn):
        import time as _time
        import psycopg
        self._held.n = max(getattr(self._held, "n", 1) - 1, 0)
        with self._cond:
            try:
                reusable = (not conn.closed and
                            conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE)
            except Exception:
                reusable = False
            if reusable:
                self._idle.append((conn, _time.monotonic()))
            else:
                self._discard(conn)
            self._cond.notify()

    def close(self):
        with self._cond:
            while self._idle:
                self._discard(self._idle.pop()[0])


_POOLS: dict = {}


def _pool_for(dsn: str):
    """The process pool for this DSN when EVO_PG_POOL_SIZE > 0, else None (one connection per transaction)."""
    import os
    try:
        size = int(os.getenv("EVO_PG_POOL_SIZE", "0"))
    except ValueError:
        size = 0
    if size <= 0:
        return None
    pool = _POOLS.get(dsn)
    if pool is None:
        try:
            wait_s = float(os.getenv("EVO_PG_POOL_WAIT_S", "30"))
        except ValueError:
            wait_s = 30.0
        pool = _POOLS.setdefault(dsn, _ConnectionPool(dsn, size, wait_s))
    return pool


def close_pools() -> None:
    for pool in list(_POOLS.values()):
        pool.close()
    _POOLS.clear()


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
        pool = _pool_for(self._dsn)
        try:
            if pool is None:
                with psycopg.connect(self._dsn, autocommit=True, connect_timeout=5, row_factory=dict_row) as conn:
                    with conn.transaction():
                        conn.execute("SET LOCAL ROLE core_app")
                        conn.execute("SELECT set_config('app.tenant_id', %s, true), "
                                     "set_config('app.project_ids', %s, true)",
                                     (str(self.scope.tenant_id), str(self.scope.project_id)))
                        yield conn
            else:
                conn = pool.acquire()
                try:
                    # SET LOCAL and set_config(..., true) end with the transaction, so a reused connection
                    # never carries another request's role or scope.
                    with conn.transaction():
                        conn.execute("SET LOCAL ROLE core_app")
                        conn.execute("SELECT set_config('app.tenant_id', %s, true), "
                                     "set_config('app.project_ids', %s, true)",
                                     (str(self.scope.tenant_id), str(self.scope.project_id)))
                        yield conn
                finally:
                    pool.release(conn)
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
        self._require_usage_guards(conn)
        guard = conn.execute("SELECT 1 FROM pg_trigger WHERE tgrelid='core.cost_reservations'::regclass "
                             "AND tgname='tenant_credit_hold' AND (tgenabled='A' OR "
                             "(tgenabled='O' AND current_setting('session_replication_role')<>'replica')) "
                             "AND tgfoid='runtime.track_tenant_credit_hold()'::regprocedure "
                             "AND NOT tgisinternal").fetchone()
        if not guard:
            raise KernelUnavailable('tenant credit guard is not installed and enabled')
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
            self._require_usage_guards(conn)
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
            self._require_usage_guards(conn)
            # Receipt ingestion takes this same reservation lock. Read usage in
            # a fresh statement after any lock wait so a committed receipt can
            # never be followed by a "not accepted" release. Legacy ctx rows,
            # estimates and zero quotes also require reconciliation.
            conn.execute("SET LOCAL ROLE ctx_gateway")
            usage = conn.execute("SELECT 1 FROM ctx.provider_usage_receipts WHERE tenant_id=%s "
                                 "AND project_id=%s AND call_id=%s LIMIT 1",
                                 (self.scope.tenant_id, self.scope.project_id, call_id)).fetchone()
            conn.execute("SET LOCAL ROLE core_app")
            if usage:
                raise KernelRejected("recorded usage requires receipt reconciliation")
            if previous.outcome == "SENT":
                conn.execute("UPDATE core.side_effect_intents SET status='FAILED' WHERE tenant_id=%s "
                             "AND kind='provider.call' AND idempotency_key=%s",
                             (self.scope.tenant_id, self._intent_key(call_id)))
            conn.execute("UPDATE core.cost_reservations SET status='RELEASED' WHERE tenant_id=%s "
                         "AND project_id=%s AND request_key=%s",
                         (self.scope.tenant_id, self.scope.project_id, str(call_id)))
            return self._read(conn, call_id)

    def _require_usage_guards(self, conn) -> None:
        installed = conn.execute("SELECT count(*) AS installed FROM pg_trigger g "
            "JOIN pg_class c ON c.oid=g.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT tgisinternal "
            "AND tgqual IS NULL AND (tgenabled='A' OR "
            "(tgenabled='O' AND current_setting('session_replication_role')<>'replica')) AND ("
            "(n.nspname='core' AND c.relname='cost_reservations' AND tgname='usage_release_guard' AND tgtype=19 "
            "AND tgfoid=to_regprocedure('runtime.reject_usage_release()')) OR "
            "(n.nspname='ctx' AND c.relname='provider_usage_receipts' AND tgname='usage_reservation_lock' AND tgtype=7 "
            "AND tgfoid=to_regprocedure('runtime.lock_usage_reservation()')))").fetchone()['installed']
        if installed != 2:
            raise KernelUnavailable('receipt and release guards are not installed and enabled')

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
            anchor = conn.execute("SELECT c.head_sha,c.author_agent_id,t.risk_level,r.policy_hash,r.harness_version "
                                  "FROM core.candidates c JOIN core.tasks t USING(tenant_id,project_id,task_id) "
                                  "JOIN core.runs r USING(tenant_id,project_id,run_id) "
                                  "WHERE c.tenant_id=%s AND c.project_id=%s AND c.candidate_id=%s "
                                  "FOR SHARE OF c,t,r",
                                  (self.scope.tenant_id,self.scope.project_id,candidate_id)).fetchone()
            if not anchor:
                raise KernelNotFound('candidate not found in scope')
            if anchor['head_sha']!=head_sha or anchor['policy_hash']!=policy_hash:
                raise KernelRejected('merge head or policy differs from the current run')
            conn.execute("SELECT core.authorize_merge(%s,%s,%s,%s,%s)",
                         (self.scope.tenant_id, self.scope.project_id, candidate_id, head_sha, policy_hash))
            if anchor['risk_level'] in {'HIGH','CRITICAL'}:
                # now() stays fixed at transaction start, including lock waits.
                # Qualification must still be valid at the actual decision time.
                current = conn.execute("WITH instant AS MATERIALIZED (SELECT clock_timestamp() AS checked_at) "
                    "SELECT EXISTS(SELECT 1 FROM core.reviews v JOIN core.reviewer_qualifications q "
                    "ON q.tenant_id=v.tenant_id AND q.agent_id=v.reviewer_agent_id CROSS JOIN instant "
                    "WHERE v.tenant_id=%s AND v.project_id=%s AND v.candidate_id=%s AND v.head_sha=%s "
                    "AND v.verdict='approve' AND v.reviewer_agent_id<>%s AND v.context_independent "
                    "AND v.spec_tests_sealed_at IS NOT NULL AND v.diff_first_read_at IS NOT NULL "
                    "AND q.risk_level=%s AND q.harness_version=%s "
                    "AND q.qualified_at<=instant.checked_at AND q.expires_at>instant.checked_at) AS qualified",
                    (self.scope.tenant_id,self.scope.project_id,candidate_id,head_sha,anchor['author_agent_id'],
                     anchor['risk_level'],anchor['harness_version'])).fetchone()['qualified']
                if not current:
                    raise KernelRejected('reviewer qualification is no longer current')

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
