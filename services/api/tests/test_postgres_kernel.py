"""Live PostgreSQL acceptance checks; EVO_TEST_DATABASE_URL must be a disposable server.

The fixture refuses existing kernel roles and creates/drops only its own database.
No provider calls, billing API, production DATABASE_URL, or model keys are used.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
import os
from pathlib import Path
import sys
import time
import subprocess
from uuid import UUID, uuid4

import pytest

if not os.getenv("EVO_TEST_DATABASE_URL"):
    pytest.skip("live PostgreSQL requires EVO_TEST_DATABASE_URL", allow_module_level=True)
psycopg = pytest.importorskip("psycopg")
from psycopg import sql  # noqa: E402
from psycopg.conninfo import make_conninfo  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evoforge.postgres_kernel import (  # noqa: E402
    BudgetRefused, KernelNotFound, KernelRejected, KernelScope, PostgresKernel, cents_to_micros,
)
from receipt_fixtures import receipt_document  # noqa: E402

PERIOD = date(2026, 10, 1)
ROLES = ["ctx_owner", "ctx_gateway", "ctx_security", "core_owner", "core_app"]


@pytest.fixture(scope="module")
def database():
    dsn = os.environ["EVO_TEST_DATABASE_URL"]
    name = "evoforge_kernel_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        exists = admin.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (ROLES,)).fetchall()
        if exists:
            pytest.fail("Refusing a server with existing Trust Kernel roles; use a dedicated test cluster")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            folder = ROOT / "docs/evoforge-v4.2/contracts/sql"
            admin.execute((folder / "roles_TEST_ONLY.sql").read_text(encoding="utf-8"))
            test_dsn = make_conninfo(dsn, dbname=name)
            with psycopg.connect(test_dsn, autocommit=True) as connection:
                connection.execute((folder / "context_plane_DRAFT.sql").read_text(encoding="utf-8"))
                connection.execute((folder / "core_DRAFT.sql").read_text(encoding="utf-8"))
                migrations = sorted((ROOT / "services/api/migrations").glob("*.sql"))
                for _ in range(2):  # extensions can be reapplied in order
                    for migration in migrations:
                        connection.execute(migration.read_text(encoding="utf-8"))
            yield test_dsn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            for role in ROLES:
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


@pytest.fixture
def funded(database):
    tenant, project = uuid4(), uuid4()
    with psycopg.connect(database, autocommit=True) as connection:
        connection.execute("INSERT INTO core.tenants(tenant_id,name,plan) VALUES (%s,'test','TEAM')", (tenant,))
        connection.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'test')", (tenant, project))
        connection.execute("INSERT INTO core.budgets VALUES (%s,%s,%s,10000000)", (tenant, project, PERIOD))
        connection.execute("INSERT INTO core.usage_ledger(tenant_id,entry_kind,customer_micros,idempotency_key,price_table_version) "
                           "VALUES (%s,'credit_grant',20000000,'fixture-credit','test')", (tenant,))
    scope = KernelScope(tenant, project)
    return {"dsn": database, "scope": scope, "kernel": PostgresKernel(database, scope)}


@pytest.fixture
def http_kernel(funded, monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    monkeypatch.setenv("EVO_KERNEL_TOKEN", "test-only-live-kernel-token-not-a-real-secret")
    monkeypatch.setenv("EVO_TENANT_ID", str(funded["scope"].tenant_id))
    monkeypatch.setenv("EVO_PROJECT_ID", str(funded["scope"].project_id))
    monkeypatch.setenv("DATABASE_URL", funded["dsn"])
    with TestClient(app, raise_server_exceptions=False,
                    headers={"Authorization": "Bearer test-only-live-kernel-token-not-a-real-secret"}) as client:
        yield client


def _receipt(funded, call_id, *, owner="platform", referenced=True, cost=80):
    scope, packet, receipt = funded["scope"], uuid4(), uuid4()
    with psycopg.connect(funded["dsn"], autocommit=True) as connection:
        connection.execute("SELECT set_config('app.tenant_id',%s,false),set_config('app.project_ids',%s,false)",
                           (str(scope.tenant_id), str(scope.project_id)))
        connection.execute("""INSERT INTO ctx.context_packets
            (tenant_id,project_id,packet_id,run_id,task_id,task_attempt_id,idempotency_key,
             seat_id,function_role,agent_id,is_author_of_candidate,channel,profile,repo_sha,
             contract_version,policy_version,policy_hash,tool_schema_hash,evidence_manifest_hash,
             lease_epoch,provider,model,cache_mode,packet_sha256,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,1,'builder',%s,true,'api','SAFE',repeat('a',40),
                    1,'test',repeat('1',64),repeat('2',64),repeat('3',64),0,'meta',
                    'muse-spark-1.3','NONE',repeat('4',64),now()+interval '1 hour')""",
            (scope.tenant_id, scope.project_id, packet, uuid4(), uuid4(), uuid4(), str(packet), uuid4()))
        connection.execute("""INSERT INTO ctx.provider_usage_receipts
            (tenant_id,project_id,receipt_id,packet_id,call_id,call_purpose,provider,model,
             provider_request_id,source,billing_owner,uncached_input,cache_write,cache_read,
             output_tokens,raw_usage_fields,cost_micros,price_table_version)
            VALUES (%s,%s,%s,%s,%s,'task_turn','meta','muse-spark-1.3',%s,%s,%s,1,0,0,1,%s,%s,'test')""",
            (scope.tenant_id, scope.project_id, receipt, packet, call_id,
             f"provider-{receipt}" if referenced else None,
             "provider_billed" if referenced else "estimated", owner, Jsonb({"tokens": 2}), cost))
    return receipt


def test_reservation_survives_new_adapter_instance_and_is_idempotent(funded):
    kernel, call = funded["kernel"], uuid4()
    first = kernel.reserve_cost(call, PERIOD, cents_to_micros(120))
    assert first.reserved_micros == 1_200_000 and first.status == "RESERVED"
    restarted = PostgresKernel(funded["dsn"], funded["scope"])
    assert restarted.reserve_cost(call, PERIOD, 1_200_000) == first
    assert restarted.reservation(call) == first
    with pytest.raises(KernelRejected):
        restarted.reserve_cost(call, PERIOD, 1_200_001)


@pytest.mark.parametrize("amount", [True, 1.5, "1", 0, -1, 2**63])
def test_money_is_strict_positive_int64(funded, amount):
    with pytest.raises(ValueError):
        funded["kernel"].reserve_cost(uuid4(), PERIOD, amount)


def test_budget_failure_leaves_neither_reservation_nor_intent(funded):
    with pytest.raises(BudgetRefused):
        funded["kernel"].reserve_cost(uuid4(), PERIOD, 10_000_001)
    with psycopg.connect(funded["dsn"]) as connection:
        for table in ("cost_reservations", "side_effect_intents"):
            count = connection.execute(sql.SQL("SELECT count(*) FROM core.{} WHERE tenant_id=%s")
                                       .format(sql.Identifier(table)), (funded["scope"].tenant_id,)).fetchone()[0]
            assert count == 0


def test_missing_prepaid_credit_refuses_before_dispatch(funded):
    with psycopg.connect(funded["dsn"], autocommit=True) as connection:
        connection.execute("INSERT INTO core.usage_ledger(tenant_id,entry_kind,customer_micros,idempotency_key,price_table_version) "
                           "VALUES (%s,'adjustment',-20000000,'remove-credit','test')", (funded["scope"].tenant_id,))
    with pytest.raises(BudgetRefused):
        funded["kernel"].reserve_cost(uuid4(), PERIOD, 100)


def test_unknown_outcome_is_durable_and_cannot_be_resent_or_refunded(funded):
    kernel, call = funded["kernel"], uuid4()
    kernel.reserve_cost(call, PERIOD, 100)
    kernel.mark_sent(call)
    kernel.mark_unknown(call)
    restarted = PostgresKernel(funded["dsn"], funded["scope"])
    assert restarted.reservation(call).outcome == "UNKNOWN_EXTERNAL_OUTCOME"
    assert restarted.reservation(call).status == "RESERVED"
    with pytest.raises(KernelRejected):
        restarted.mark_sent(call)
    with pytest.raises(KernelRejected):
        restarted.release_not_accepted(call)


def test_definitely_unaccepted_call_releases_budget_idempotently(funded):
    kernel, call = funded["kernel"], uuid4()
    kernel.reserve_cost(call, PERIOD, 100)
    kernel.mark_sent(call)
    assert kernel.release_not_accepted(call).status == "RELEASED"
    assert kernel.release_not_accepted(call).outcome == "FAILED"
    with pytest.raises(KernelRejected):
        kernel.mark_sent(call)


def test_receipt_reconciles_unknown_and_charges_exactly_once(funded):
    kernel, call = funded["kernel"], uuid4()
    kernel.reserve_cost(call, PERIOD, 100)
    kernel.mark_sent(call)
    kernel.mark_unknown(call)
    receipt = _receipt(funded, call)
    result = kernel.settle_reservation(call, receipt, 110)
    assert result.status == "COMMITTED" and result.outcome == "CONFIRMED"
    assert result.actual_micros == 110  # over-reservation usage is recorded, never hidden
    assert kernel.settle_reservation(call, receipt, 110) == result
    with pytest.raises(KernelRejected):
        kernel.settle_reservation(call, receipt, 111)
    with psycopg.connect(funded["dsn"]) as connection:
        rows = connection.execute("SELECT customer_micros,provider_cost_micros,receipt_id FROM core.usage_ledger "
                                  "WHERE tenant_id=%s AND entry_kind='model_usage'",
                                  (funded["scope"].tenant_id,)).fetchall()
        assert rows == [(-110, 80, receipt)]


@pytest.mark.parametrize("bad_receipt", ["different-call", "byok", "missing-reference", "missing"])
def test_unbound_receipt_never_commits_or_releases_reserved_credit(funded, bad_receipt):
    kernel, call = funded["kernel"], uuid4()
    kernel.reserve_cost(call, PERIOD, 100)
    kernel.mark_sent(call)
    receipt = uuid4() if bad_receipt == "missing" else _receipt(
        funded, uuid4() if bad_receipt == "different-call" else call,
        owner="byok_customer" if bad_receipt == "byok" else "platform",
        referenced=bad_receipt != "missing-reference",
    )
    with pytest.raises(KernelRejected):
        kernel.settle_reservation(call, receipt, 100)
    assert kernel.reservation(call).status == "RESERVED"
    assert kernel.reservation(call).outcome == "SENT"


def test_tenant_and_project_scope_cannot_read_another_reservation(funded):
    call = uuid4()
    funded["kernel"].reserve_cost(call, PERIOD, 100)
    for scope in (KernelScope(uuid4(), funded["scope"].project_id),
                  KernelScope(funded["scope"].tenant_id, uuid4())):
        with pytest.raises(KernelRejected):
            PostgresKernel(funded["dsn"], scope).reservation(call)
    assert funded["kernel"].reservation(call).reserved_micros == 100


def test_runtime_transaction_cannot_bypass_row_level_security(funded):
    with pytest.raises(KernelRejected):
        with funded["kernel"]._transaction() as connection:
            connection.execute("INSERT INTO core.tenants(tenant_id,name,plan) VALUES (%s,'foreign','TEAM')", (uuid4(),))


def test_concurrent_duplicate_requests_reserve_once(funded):
    call = uuid4()
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda _: funded["kernel"].reserve_cost(call, PERIOD, 100), range(8)))
    assert all(row == results[0] for row in results)


def test_concurrent_distinct_calls_cannot_exceed_budget(funded):
    with psycopg.connect(funded["dsn"], autocommit=True) as connection:
        connection.execute("UPDATE core.budgets SET cap_micros=150 WHERE tenant_id=%s", (funded["scope"].tenant_id,))
    def reserve(_):
        try:
            funded["kernel"].reserve_cost(uuid4(), PERIOD, 100)
            return True
        except BudgetRefused:
            return False
    with ThreadPoolExecutor(max_workers=8) as workers:
        assert sum(workers.map(reserve, range(8))) == 1


def test_merge_authorization_is_enforced_by_database_and_never_merges_itself(funded, http_kernel):
    scope, kernel = funded["scope"], funded["kernel"]
    author, reviewer, run, task, candidate = (uuid4() for _ in range(5))
    with psycopg.connect(funded["dsn"], autocommit=True) as connection:
        for agent in (author, reviewer):
            connection.execute("INSERT INTO core.agents(tenant_id,agent_id,kind) VALUES (%s,%s,'provider_api')", (scope.tenant_id, agent))
        connection.execute("INSERT INTO core.runs(tenant_id,project_id,run_id,objective_version,topology,harness_version,policy_hash) "
                           "VALUES (%s,%s,%s,1,'SINGLE','test',%s)", (scope.tenant_id, scope.project_id, run, '1'*64))
        connection.execute("INSERT INTO core.tasks(tenant_id,project_id,task_id,run_id,risk_level) VALUES (%s,%s,%s,%s,'LOW')",
                           (scope.tenant_id, scope.project_id, task, run))
        connection.execute("INSERT INTO core.candidates(tenant_id,project_id,candidate_id,task_id,author_agent_id,base_sha,head_sha) "
                           "VALUES (%s,%s,%s,%s,%s,%s,%s)", (scope.tenant_id, scope.project_id, candidate, task, author, 'a'*40, 'b'*40))
        original_status = connection.execute("SELECT status FROM core.candidates WHERE candidate_id=%s", (candidate,)).fetchone()[0]
    with pytest.raises(KernelRejected):
        kernel.authorize_merge(candidate, 'b'*40, '1'*64)
    body = {"candidate_id": str(candidate), "head_sha": 'b'*40, "policy_hash": '1'*64}
    assert http_kernel.post('/v1/kernel/merge-authorizations', json=body).status_code == 409
    with psycopg.connect(funded["dsn"], autocommit=True) as connection:
        for gate in ["G0_SCOPE", "G1_IMPACTED", "G2_REQUIRED", "GH_INTEGRITY", "GR_REVIEW", "G4_MERGE_HEAD"]:
            connection.execute("INSERT INTO core.gate_results(tenant_id,project_id,candidate_id,gate,result,head_sha,policy_hash,runner_image_digest,evidence_sha256) "
                               "VALUES (%s,%s,%s,%s,'PASS',%s,%s,'sha256:test',%s)",
                               (scope.tenant_id, scope.project_id, candidate, gate, 'b'*40, '1'*64, 'e'*64))
        connection.execute("INSERT INTO core.reviews(tenant_id,project_id,candidate_id,reviewer_agent_id,verdict,head_sha) "
                           "VALUES (%s,%s,%s,%s,'approve',%s)", (scope.tenant_id, scope.project_id, candidate, reviewer, 'b'*40))
    kernel.authorize_merge(candidate, 'b'*40, '1'*64)
    assert http_kernel.post('/v1/kernel/merge-authorizations', json=body).json()['authorized'] is True
    assert http_kernel.post('/v1/kernel/merge-authorizations', json={**body, 'head_sha': 'c'*40}).status_code == 409
    with pytest.raises(KernelRejected):
        kernel.authorize_merge(candidate, 'c'*40, '1'*64)
    with psycopg.connect(funded["dsn"]) as connection:
        assert connection.execute("SELECT status FROM core.candidates WHERE candidate_id=%s", (candidate,)).fetchone()[0] == original_status


def _http_reserve(client, call, amount=100):
    return client.post('/v1/kernel/reservations', json={
        'call_id': str(call), 'period_start': PERIOD.isoformat(), 'amount_micros': amount})


def test_http_reservation_survives_requests_and_unknown_cannot_be_retried(funded, http_kernel):
    call = uuid4()
    assert _http_reserve(http_kernel, call).status_code == 200
    assert http_kernel.get(f'/v1/kernel/reservations/{call}').json()['status'] == 'RESERVED'
    assert http_kernel.post(f'/v1/kernel/reservations/{call}/sent').status_code == 200
    assert http_kernel.post(f'/v1/kernel/reservations/{call}/unknown').status_code == 200
    assert http_kernel.post(f'/v1/kernel/reservations/{call}/release-not-accepted').status_code == 409
    assert http_kernel.post(f'/v1/kernel/reservations/{call}/sent').status_code == 409
    assert funded['kernel'].reservation(call).outcome == 'UNKNOWN_EXTERNAL_OUTCOME'


def test_http_receipt_settlement_is_durable_and_idempotent(funded, http_kernel):
    call = uuid4()
    assert _http_reserve(http_kernel, call).status_code == 200
    assert http_kernel.post(f'/v1/kernel/reservations/{call}/sent').status_code == 200
    receipt = _receipt(funded, call)
    body = {'receipt_id': str(receipt), 'customer_micros': 100}
    for _ in range(2):
        response = http_kernel.post(f'/v1/kernel/reservations/{call}/settle', json=body)
        assert response.status_code == 200 and response.json()['status'] == 'COMMITTED'
    assert http_kernel.post(f'/v1/kernel/reservations/{call}/settle', json={**body, 'customer_micros': 101}).status_code == 409
    with psycopg.connect(funded['dsn']) as connection:
        assert connection.execute("SELECT count(*) FROM core.usage_ledger WHERE tenant_id=%s AND entry_kind='model_usage'",
                                  (funded['scope'].tenant_id,)).fetchone()[0] == 1


def test_http_budget_refusal_and_cross_project_read_are_fail_closed(funded, http_kernel, monkeypatch):
    assert _http_reserve(http_kernel, uuid4(), 10_000_001).status_code == 402
    call = uuid4()
    assert _http_reserve(http_kernel, call).status_code == 200
    monkeypatch.setenv('EVO_PROJECT_ID', str(uuid4()))
    foreign = http_kernel.get(f'/v1/kernel/reservations/{call}')
    missing = http_kernel.get(f'/v1/kernel/reservations/{uuid4()}')
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()


def test_http_unavailable_database_never_uses_memory_fallback(funded, http_kernel, monkeypatch):
    from evoforge import ledger
    def forbidden(*args, **kwargs):
        pytest.fail('database failure must not use the demo ledger')
    monkeypatch.setattr(ledger, 'reserve', forbidden)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://hidden:must-not-leak@127.0.0.1:1/unavailable')
    response = _http_reserve(http_kernel, uuid4())
    assert response.status_code == 503 and 'must-not-leak' not in response.text


def _packet(funded, *, issued="now()", expires="now()+interval '1 hour'"):
    """Test-owned timestamps only; never interpolate user/provider input into SQL."""
    scope, packet = funded["scope"], uuid4()
    with psycopg.connect(funded["dsn"], autocommit=True) as connection:
        connection.execute(sql.SQL("""INSERT INTO ctx.context_packets
            (tenant_id,project_id,packet_id,run_id,task_id,task_attempt_id,idempotency_key,
             seat_id,function_role,agent_id,is_author_of_candidate,channel,profile,repo_sha,
             contract_version,policy_version,policy_hash,tool_schema_hash,evidence_manifest_hash,
             lease_epoch,provider,model,cache_mode,packet_sha256,issued_at,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,1,'builder',%s,true,'api','SAFE',repeat('a',40),
                    1,'test',repeat('1',64),repeat('2',64),repeat('3',64),0,'meta',
                    'muse-spark-1.3','NONE',repeat('4',64),{},{})""")
            .format(sql.SQL(issued), sql.SQL(expires)),
            (scope.tenant_id, scope.project_id, packet, uuid4(), uuid4(), uuid4(), str(packet), uuid4()))
    return packet


def _document(funded, *, sent=True, unknown=False, packet=None):
    packet = packet or _packet(funded)
    call, kernel = uuid4(), funded["kernel"]
    kernel.reserve_cost(call, PERIOD, 100)
    if sent:
        kernel.mark_sent(call)
    if unknown:
        kernel.mark_unknown(call)
    scope = funded["scope"]
    return receipt_document(tenant=scope.tenant_id, project=scope.project_id, packet=packet, call=call)


def test_document_and_ctx_row_persist_atomically_and_reconcile_unknown_once(funded):
    document, kernel = _document(funded, unknown=True), funded["kernel"]
    rid, call = document["receipt_id"], document["call_id"]
    recorded = kernel.record_receipt(document)
    assert recorded == {**document, "ledger_entry_id": None}
    assert kernel.record_receipt(dict(reversed(list(document.items())))) == recorded
    restarted = PostgresKernel(funded["dsn"], funded["scope"])
    assert restarted.receipt_document(rid) == recorded
    state = restarted.settle_from_receipt(rid)
    assert state.status == "COMMITTED" and state.actual_micros == 110
    assert restarted.settle_from_receipt(rid) == state
    closed = restarted.receipt_document(rid)
    assert closed["ledger_entry_id"] is not None
    assert restarted.record_receipt(document) == closed
    with psycopg.connect(funded["dsn"]) as connection:
        assert connection.execute("SELECT customer_micros,provider_cost_micros,receipt_id,entry_id "
                                  "FROM core.usage_ledger WHERE tenant_id=%s AND entry_kind='model_usage'",
                                  (funded["scope"].tenant_id,)).fetchall() == [
                                      (-110, 80, UUID(rid), UUID(closed["ledger_entry_id"]))]
    assert kernel.reservation(call).outcome == "CONFIRMED"


def test_stored_quote_cannot_be_overridden_by_legacy_settlement(funded):
    document, kernel = _document(funded), funded["kernel"]
    kernel.record_receipt(document)
    with pytest.raises(KernelRejected):
        kernel.settle_reservation(document["call_id"], document["receipt_id"], 111)
    assert kernel.reservation(document["call_id"]).status == "RESERVED"
    assert kernel.settle_from_receipt(document["receipt_id"]).actual_micros == 110


def test_concurrent_receipt_replays_store_and_settle_only_once(funded):
    document, kernel = _document(funded), funded["kernel"]
    with ThreadPoolExecutor(max_workers=6) as workers:
        rows = list(workers.map(lambda _: kernel.record_receipt(document), range(6)))
    assert all(row == rows[0] for row in rows)
    with ThreadPoolExecutor(max_workers=6) as workers:
        states = list(workers.map(lambda _: kernel.settle_from_receipt(document["receipt_id"]), range(6)))
    assert all(state == states[0] for state in states)


@pytest.mark.parametrize("change", ["price", "usage", "duplicate-call", "duplicate-provider-reference"])
def test_changed_or_duplicate_receipt_never_leaves_partial_rows(funded, change):
    from copy import deepcopy
    document, kernel = _document(funded), funded["kernel"]
    kernel.record_receipt(document)
    other = deepcopy(document)
    if change == "price":
        other["customer_price_micros"] += 1
    elif change == "usage":
        other["raw_usage_fields"]["completion_tokens"] += 1
    else:
        other["receipt_id"] = str(uuid4())
        if change == "duplicate-call":
            other["provider_request_id"] += "-different"
        else:
            second = _document(funded)
            other.update(call_id=second["call_id"], reservation_key=second["call_id"], packet_id=second["packet_id"])
    with pytest.raises(KernelRejected):
        kernel.record_receipt(other)
    with psycopg.connect(funded["dsn"]) as connection:
        for table in ("ctx.provider_usage_receipts", "runtime.provider_receipt_documents"):
            assert connection.execute(sql.SQL("SELECT count(*) FROM {} WHERE tenant_id=%s")
                                      .format(sql.SQL(table)), (funded["scope"].tenant_id,)).fetchone()[0] == 1


@pytest.mark.parametrize("problem", ["unsent", "released", "missing-call", "foreign-scope", "model", "provider", "packet", "expired", "late-packet"])
def test_receipt_requires_a_matching_context_before_reserved_dispatch(funded, problem):
    document, kernel = _document(funded, sent=problem != "unsent"), funded["kernel"]
    if problem == "released":
        kernel.release_not_accepted(document["call_id"])
    elif problem == "missing-call":
        document["call_id"] = document["reservation_key"] = str(uuid4())
    elif problem == "foreign-scope":
        document["project_id"] = str(uuid4())
    elif problem in {"model", "provider"}:
        document[problem] = "other" if problem == "provider" else "other-model"
    elif problem == "packet":
        document["packet_id"] = str(uuid4())
    elif problem == "expired":
        document["packet_id"] = str(_packet(funded, issued="now()-interval '2 hours'", expires="now()-interval '1 hour'"))
    elif problem == "late-packet":
        document["packet_id"] = str(_packet(funded))
    with pytest.raises(KernelRejected):
        kernel.record_receipt(document)
    with psycopg.connect(funded["dsn"]) as connection:
        for table in ("ctx.provider_usage_receipts", "runtime.provider_receipt_documents"):
            assert connection.execute(sql.SQL("SELECT count(*) FROM {} WHERE tenant_id=%s")
                                      .format(sql.SQL(table)), (funded["scope"].tenant_id,)).fetchone()[0] == 0


def test_receipt_getter_and_rls_cannot_expose_foreign_scope(funded):
    document, kernel = _document(funded), funded["kernel"]
    kernel.record_receipt(document)
    for scope in (KernelScope(uuid4(), funded["scope"].project_id), KernelScope(funded["scope"].tenant_id, uuid4())):
        foreign = PostgresKernel(funded["dsn"], scope)
        with pytest.raises(KernelNotFound):
            foreign.receipt_document(document["receipt_id"])
        with foreign._transaction() as connection:
            connection.execute("SET LOCAL ROLE ctx_gateway")
            assert connection.execute("SELECT count(*) FROM runtime.provider_receipt_documents").fetchone()["count"] == 0


def test_receipt_documents_are_append_only_even_for_database_owner(funded):
    document = _document(funded)
    funded["kernel"].record_receipt(document)
    with psycopg.connect(funded["dsn"], autocommit=True) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("UPDATE runtime.provider_receipt_documents SET document_sha256=repeat('0',64) WHERE receipt_id=%s",
                               (document["receipt_id"],))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("DELETE FROM runtime.provider_receipt_documents WHERE receipt_id=%s", (document["receipt_id"],))


def test_receipt_digest_survives_raw_usage_numeric_json_round_trip(funded):
    document, kernel = _document(funded), funded["kernel"]
    document["raw_usage_fields"].update(large=1e20, signed_zero=-0.0, fraction=0.0123)
    recorded = kernel.record_receipt(document)
    assert kernel.receipt_document(document["receipt_id"]) == recorded
    assert kernel.settle_from_receipt(document["receipt_id"]).status == "COMMITTED"


def test_zero_quote_is_preserved_without_fake_charge_or_refund(funded):
    document, kernel = _document(funded), funded["kernel"]
    document["cost_micros"] = document["customer_price_micros"] = 0
    kernel.record_receipt(document)
    with pytest.raises(ValueError):
        kernel.settle_from_receipt(document["receipt_id"])
    assert kernel.reservation(document["call_id"]).status == "RESERVED"


def test_http_receipt_ingestion_scope_and_quote_bound_settlement(funded, http_kernel, monkeypatch):
    document = _document(funded)
    rid = document["receipt_id"]
    response = http_kernel.post('/v1/kernel/receipts', json=document)
    assert response.status_code == 200, response.text
    assert http_kernel.get(f'/v1/kernel/receipts/{rid}').json()['source'] == 'provider_billed'
    legacy = http_kernel.post(f'/v1/kernel/reservations/{document["call_id"]}/settle',
                              json={'receipt_id': rid, 'customer_micros': 111})
    assert legacy.status_code == 409
    assert http_kernel.post(f'/v1/kernel/receipts/{rid}/settle', json={'customer_micros': 111}).status_code == 422
    assert http_kernel.post(f'/v1/kernel/receipts/{rid}/settle', json={}).json()['status'] == 'COMMITTED'
    assert http_kernel.get(f'/v1/kernel/receipts/{rid}').json()['ledger_entry_id'] is not None
    monkeypatch.setenv('EVO_PROJECT_ID', str(uuid4()))
    foreign = http_kernel.get(f'/v1/kernel/receipts/{rid}')
    missing = http_kernel.get(f'/v1/kernel/receipts/{uuid4()}')
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()


def _builder_packet(funded, *, role="builder", model="muse-spark-1.3", expires_s=3600, base_sha='a'*40):
    """Real claim_task/fence plus a synthetic trusted Gateway packet/consent."""
    scope = funded["scope"]
    agent, run, task, packet = (uuid4() for _ in range(4))
    with psycopg.connect(funded["dsn"], autocommit=True) as connection:
        connection.execute("INSERT INTO core.agents(tenant_id,agent_id,kind,join_state,connection_state) "
                           "VALUES (%s,%s,'provider_api','AUTHORIZED','READY')", (scope.tenant_id, agent))
        connection.execute("INSERT INTO core.runs(tenant_id,project_id,run_id,objective_version,topology,harness_version,policy_hash) "
                           "VALUES (%s,%s,%s,1,'SINGLE','test',repeat('1',64))", (scope.tenant_id, scope.project_id, run))
        for state in ("QUEUED", "RUNNING"):
            connection.execute("UPDATE core.runs SET status=%s WHERE run_id=%s", (state, run))
        connection.execute("INSERT INTO core.tasks(tenant_id,project_id,task_id,run_id,risk_level,base_sha) "
                           "VALUES (%s,%s,%s,%s,'LOW',%s)", (scope.tenant_id, scope.project_id, task, run, base_sha))
        epoch = connection.execute("SELECT core.claim_task(%s,%s,%s,%s,interval '1 hour')",
                                   (scope.tenant_id, scope.project_id, task, agent)).fetchone()[0]
        connection.execute("UPDATE core.tasks SET status='RUNNING' WHERE task_id=%s", (task,))
        connection.execute("""INSERT INTO ctx.context_packets
            (tenant_id,project_id,packet_id,run_id,task_id,task_attempt_id,idempotency_key,
             seat_id,function_role,agent_id,candidate_id,is_author_of_candidate,channel,profile,repo_sha,
             contract_version,policy_version,policy_hash,tool_schema_hash,evidence_manifest_hash,
             lease_epoch,provider,model,cache_mode,packet_sha256,issued_at,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,'api','SAFE',%s,
                    1,'test',repeat('1',64),repeat('2',64),repeat('3',64),%s,'meta',%s,'NONE',repeat('4',64),
                    now()+%s*interval '1 second',now()+%s*interval '1 second')""",
            (scope.tenant_id, scope.project_id, packet, run, task, uuid4(), str(packet), role, agent,
             uuid4() if role in {"critic", "verifier"} else None, role not in {"critic", "verifier"}, base_sha, epoch, model,
             -7200 if expires_s < 0 else 0, expires_s))
        connection.execute("INSERT INTO core.provider_allowlist "
                           "(tenant_id,project_id,provider,model_glob,data_consent_at,consented_by) "
                           "VALUES (%s,%s,'meta','muse-spark-*',now(),%s) ON CONFLICT DO NOTHING",
                           (scope.tenant_id, scope.project_id, uuid4()))
    return {"packet": packet, "agent": agent, "run": run, "task": task, "epoch": epoch}


def _prepare(funded, packet, call=None, **kwargs):
    return funded["kernel"].prepare_builder_call(call or uuid4(), PERIOD, 100, packet,
                                                "synthetic-test-v1", **kwargs)


def test_builder_context_reservation_dispatch_and_document_settlement_are_durable(funded):
    context, kernel, call = _builder_packet(funded), funded["kernel"], uuid4()
    prepared = _prepare(funded, context["packet"], call)
    assert prepared["model"] == "muse-spark-1.3" and prepared["provider"] == "meta"
    assert prepared["reservation"].outcome == "RESERVED" and prepared["lease_epoch"] == 1
    restarted = PostgresKernel(funded["dsn"], funded["scope"])
    assert restarted.builder_call(call) == prepared
    assert _prepare(funded, context["packet"], call) == prepared
    assert restarted.mark_sent(call).outcome == "SENT"
    assert _prepare(funded, context["packet"], call)["reservation"].outcome == "SENT"
    with pytest.raises(KernelRejected):
        restarted.mark_sent(call)
    scope = funded["scope"]
    document = receipt_document(tenant=scope.tenant_id, project=scope.project_id, packet=context["packet"], call=call)
    restarted.record_receipt(document)
    assert restarted.settle_from_receipt(document["receipt_id"]).status == "COMMITTED"
    assert restarted.receipt_document(document["receipt_id"])["ledger_entry_id"] is not None


@pytest.mark.parametrize("problem", ["consent", "future-consent", "model", "role", "expired", "agent", "lease", "epoch", "base", "policy", "objective", "paused", "task"])
def test_builder_preflight_refusal_rolls_back_budget_intent_and_binding(funded, problem):
    context = _builder_packet(funded, model="other-model" if problem == "model" else "muse-spark-1.3",
                              role="critic" if problem == "role" else "builder", expires_s=-1 if problem == "expired" else 3600)
    with psycopg.connect(funded["dsn"], autocommit=True) as connection:
        if problem == "consent":
            connection.execute("UPDATE core.provider_allowlist SET revoked_at=now() WHERE tenant_id=%s", (funded["scope"].tenant_id,))
        elif problem == "future-consent":
            connection.execute("UPDATE core.provider_allowlist SET data_consent_at=now()+interval '1 hour' WHERE tenant_id=%s", (funded["scope"].tenant_id,))
        elif problem == "agent":
            connection.execute("UPDATE core.agents SET connection_state='OFFLINE' WHERE agent_id=%s", (context["agent"],))
        elif problem == "lease":
            connection.execute("UPDATE core.tasks SET lease_expires_at=now()-interval '1 hour' WHERE task_id=%s", (context["task"],))
        elif problem == "epoch":
            connection.execute("UPDATE core.tasks SET lease_epoch=lease_epoch+1 WHERE task_id=%s", (context["task"],))
        elif problem == "base":
            connection.execute("UPDATE core.tasks SET base_sha=repeat('b',40) WHERE task_id=%s", (context["task"],))
        elif problem == "policy":
            connection.execute("UPDATE core.runs SET policy_hash=repeat('2',64) WHERE run_id=%s", (context["run"],))
        elif problem == "objective":
            connection.execute("UPDATE core.runs SET objective_version=2 WHERE run_id=%s", (context["run"],))
        elif problem == "paused":
            for state in ("PAUSING", "PAUSED"):
                connection.execute("UPDATE core.runs SET status=%s WHERE run_id=%s", (state, context["run"]))
        elif problem == "task":
            connection.execute("UPDATE core.tasks SET status='BLOCKED' WHERE task_id=%s", (context["task"],))
    with pytest.raises(KernelRejected):
        _prepare(funded, context["packet"])
    with psycopg.connect(funded["dsn"]) as connection:
        for table in ("core.cost_reservations", "core.side_effect_intents", "runtime.builder_call_bindings"):
            assert connection.execute(sql.SQL("SELECT count(*) FROM {} WHERE tenant_id=%s").format(sql.SQL(table)),
                                      (funded["scope"].tenant_id,)).fetchone()[0] == 0


@pytest.mark.parametrize("change", ["consent", "packet", "lease", "epoch", "model"])
def test_dispatch_rechecks_changes_after_reservation_without_sending_or_refunding(funded, change):
    context, call, kernel = _builder_packet(funded), uuid4(), funded["kernel"]
    _prepare(funded, context["packet"], call)
    with psycopg.connect(funded["dsn"], autocommit=True) as connection:
        if change == "consent":
            connection.execute("UPDATE core.provider_allowlist SET revoked_at=now() WHERE tenant_id=%s", (funded["scope"].tenant_id,))
        elif change == "packet":
            connection.execute("UPDATE ctx.context_packets SET status='STALE',status_reason='goal_changed' WHERE packet_id=%s", (context["packet"],))
        elif change == "lease":
            connection.execute("UPDATE core.tasks SET lease_expires_at=now()-interval '1 second' WHERE task_id=%s", (context["task"],))
        elif change == "epoch":
            connection.execute("UPDATE core.tasks SET lease_epoch=lease_epoch+1 WHERE task_id=%s", (context["task"],))
    with pytest.raises(KernelRejected):
        kernel.mark_sent(call, "unapproved-replacement" if change == "model" else "muse-spark-1.3")
    state = kernel.reservation(call)
    assert state.status == state.outcome == "RESERVED"
    assert kernel.release_not_accepted(call).status == "RELEASED"


def test_builder_call_cannot_change_packet_or_price_version_on_replay(funded):
    first, second, call = _builder_packet(funded), _builder_packet(funded), uuid4()
    _prepare(funded, first["packet"], call)
    with pytest.raises(KernelRejected):
        _prepare(funded, second["packet"], call)
    with pytest.raises(KernelRejected):
        funded["kernel"].prepare_builder_call(call, PERIOD, 100, first["packet"], "new-price")


@pytest.mark.parametrize("change", ["packet", "price", "purpose"])
def test_bound_builder_receipt_cannot_use_another_context_or_price(funded, change):
    first, second, call, kernel = _builder_packet(funded), _builder_packet(funded), uuid4(), funded["kernel"]
    _prepare(funded, first["packet"], call)
    kernel.mark_sent(call)
    scope = funded["scope"]
    document = receipt_document(tenant=scope.tenant_id, project=scope.project_id, packet=first["packet"], call=call)
    if change == "packet":
        document["packet_id"] = str(second["packet"])
    elif change == "price":
        document["price_table_version"] = "other-price"
    else:
        document["call_purpose"] = "review_chunk"
    with pytest.raises(KernelRejected):
        kernel.record_receipt(document)
    assert kernel.reservation(call).outcome == "SENT"


def test_bound_builder_call_cannot_settle_through_ctx_only_legacy_receipt(funded):
    context, call, kernel = _builder_packet(funded), uuid4(), funded["kernel"]
    _prepare(funded, context["packet"], call)
    kernel.mark_sent(call)
    bare = _receipt(funded, call)
    with pytest.raises(KernelRejected):
        kernel.settle_reservation(call, bare, 110)
    assert kernel.reservation(call).status == "RESERVED"


def test_builder_preparation_is_concurrent_idempotent_and_scope_isolated(funded):
    context, call = _builder_packet(funded), uuid4()
    with ThreadPoolExecutor(max_workers=6) as workers:
        rows = list(workers.map(lambda _: _prepare(funded, context["packet"], call), range(6)))
    assert all(row == rows[0] for row in rows)
    for scope in (KernelScope(uuid4(), funded["scope"].project_id), KernelScope(funded["scope"].tenant_id, uuid4())):
        with pytest.raises(KernelNotFound):
            PostgresKernel(funded["dsn"], scope).builder_call(call)


def test_context_cannot_be_attached_after_call_was_already_sent(funded):
    context, call, kernel = _builder_packet(funded), uuid4(), funded["kernel"]
    kernel.reserve_cost(call, PERIOD, 100)
    kernel.mark_sent(call)
    with pytest.raises(KernelRejected):
        _prepare(funded, context["packet"], call)


def test_http_builder_policy_is_server_owned_and_dispatch_refuses_revoked_packet(funded, http_kernel, monkeypatch):
    monkeypatch.setenv("EVO_PRICE_TABLE_VERSION", "synthetic-test-v1")
    context, call = _builder_packet(funded), uuid4()
    body = {'call_id': str(call), 'packet_id': str(context['packet']), 'period_start': PERIOD.isoformat(), 'amount_micros': 100}
    response = http_kernel.post('/v1/kernel/builder-calls', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['model'] == 'muse-spark-1.3'
    assert http_kernel.get(f'/v1/kernel/builder-calls/{call}').json()['reservation']['outcome'] == 'RESERVED'
    assert http_kernel.post('/v1/kernel/builder-calls', json={**body, 'price_table_version': 'forged'}).status_code == 422
    with psycopg.connect(funded['dsn'], autocommit=True) as connection:
        connection.execute("UPDATE ctx.context_packets SET status='REVOKED',status_reason='revoked' WHERE packet_id=%s", (context['packet'],))
    assert http_kernel.post(f'/v1/kernel/reservations/{call}/sent').status_code == 409
    assert funded['kernel'].reservation(call).outcome == 'RESERVED'


def test_builder_budget_refusal_and_missing_packet_leave_no_binding(funded):
    context, kernel = _builder_packet(funded), funded["kernel"]
    with pytest.raises(BudgetRefused):
        kernel.prepare_builder_call(uuid4(), PERIOD, 10_000_001, context["packet"], "synthetic-test-v1")
    with pytest.raises(KernelNotFound):
        _prepare(funded, uuid4())
    with psycopg.connect(funded["dsn"]) as connection:
        assert connection.execute("SELECT count(*) FROM runtime.builder_call_bindings WHERE tenant_id=%s",
                                  (funded["scope"].tenant_id,)).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM core.cost_reservations WHERE tenant_id=%s",
                                  (funded["scope"].tenant_id,)).fetchone()[0] == 0


def test_builder_packet_created_after_cost_reservation_cannot_retroactively_bind(funded):
    kernel, call = funded["kernel"], uuid4()
    kernel.reserve_cost(call, PERIOD, 100)
    context = _builder_packet(funded)
    with pytest.raises(KernelRejected):
        _prepare(funded, context["packet"], call)
    with pytest.raises(KernelNotFound):
        kernel.builder_call(call)
    assert kernel.reservation(call).outcome == "RESERVED"


def test_builder_bindings_are_immutable_and_rls_scoped(funded):
    context, call = _builder_packet(funded), uuid4()
    _prepare(funded, context["packet"], call)
    foreign = PostgresKernel(funded["dsn"], KernelScope(funded["scope"].tenant_id, uuid4()))
    with foreign._transaction() as connection:
        assert connection.execute("SELECT count(*) FROM runtime.builder_call_bindings").fetchone()["count"] == 0
    with psycopg.connect(funded["dsn"], autocommit=True) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("UPDATE runtime.builder_call_bindings SET price_table_version='changed' WHERE call_id=%s", (call,))


def test_preflight_uses_wall_clock_after_waiting_for_tenant_reservation_lock(funded):
    context = _builder_packet(funded)
    with psycopg.connect(funded["dsn"]) as control:
        control.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                        (f"core.credit:{funded['scope'].tenant_id}",))
        with ThreadPoolExecutor(max_workers=1) as worker:
            pending = worker.submit(_prepare, funded, context["packet"])
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    # pg_stat_activity caches a snapshot for this transaction;
                    # pg_locks is live and shows the newly connected worker.
                    waiting = control.execute("SELECT EXISTS(SELECT 1 FROM pg_locks l "
                                              "WHERE l.database=(SELECT oid FROM pg_database "
                                              "WHERE datname=current_database()) AND l.locktype='advisory' "
                                              "AND NOT l.granted)").fetchone()[0]
                    if waiting:
                        break
                    time.sleep(0.01)
                assert waiting, "worker must begin its transaction before expiry is changed"
                # now() in the waiting transaction predates this expiry. Using
                # only core.assert_fencing's transaction clock would accept it.
                control.execute("UPDATE core.tasks SET lease_expires_at=clock_timestamp() WHERE task_id=%s",
                                (context["task"],))
            finally:
                control.commit()  # always release the worker, even on assertion failure
            with pytest.raises(KernelRejected):
                pending.result(timeout=10)


@pytest.fixture
def durable_api(funded, monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv('EVO_STATE_BACKEND', 'postgres')
    monkeypatch.setenv('DATABASE_URL', funded['dsn'])
    monkeypatch.setenv('EVO_TENANT_ID', str(funded['scope'].tenant_id))
    monkeypatch.setenv('EVO_PROJECT_ID', str(funded['scope'].project_id))
    monkeypatch.setenv('EVO_REQUIRE_ID_TOKEN', '0')
    monkeypatch.delenv('MODEL_API_KEY', raising=False)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client


def test_request_evidence_and_private_review_survive_a_new_api_process(funded, durable_api, monkeypatch, tmp_path):
    """Synthetic Critic, real local Runner and PostgreSQL; never a provider call."""
    import json
    import main
    from evoforge import postgres_state
    repo = tmp_path / 'durable-source'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
    git('init', '-q')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    (repo / 'value.py').write_text('result = 2\n', encoding='utf-8')
    git('add', 'value.py')
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    monkeypatch.setenv('EVO_ALLOW_LOCAL_REPOS', '1')
    monkeypatch.setenv('EVO_REPO_ROOTS', str(tmp_path))
    monkeypatch.setenv('EVO_RUNNER_URL', '')
    canary = 'DURABLE_SEALED_CANARY_881'
    sealed = [{'kind': kind, 'code': f'# {canary}\nfrom value import result\ndef test_{kind}():\n    assert result == 3\n'}
              for kind in ('compositional', 'negative', 'boundary')]
    monkeypatch.setattr(main.broker_meta, 'call_critic', lambda *args, **kwargs: {
        'stub': False, 'model': 'muse-spark-1.3', 'sealed_tests': sealed, 'review': {'result': 'PASS'}})
    review = durable_api.post('/v1/candidates/review', json={'goal_contract': 'value must be 3'})
    assert review.status_code == 200 and canary not in review.text
    review_id = review.json()['evidence_id']
    assert postgres_state.ScopedRecords('records')[review_id]['review']['sealed_tests'] == sealed
    # No process-local evidence or links can supply these later reads.
    main._evidence._memory.clear()
    main.evidence_chain._LINKS.clear()
    response = durable_api.post('/v1/runs', json={
        'source_repo': str(repo), 'base_sha': base,
        'diff': '--- a/value.py\n+++ b/value.py\n@@ -1 +1 @@\n-result = 2\n+result = 3\n',
        'tests': [{'code': 'from value import result\ndef test_value():\n    assert result == 3\n'}],
        'review_evidence_id': review_id,
    })
    assert response.status_code == 200, response.text
    assert response.json()['run']['visible']['pass'] == 1
    assert response.json()['run']['heldout']['pass'] == 3
    evidence_id = response.json()['evidence_id']
    script = """import json,os
import main
from fastapi.testclient import TestClient
from evoforge.postgres_state import ScopedRecords
with TestClient(main.app) as c:
    response=c.get('/v1/evidence/'+os.environ['FIXTURE_EVIDENCE_ID'])
    body=response.json()
    events=[c.get('/v1/events/'+x['event_id']).json() for x in body['chain'] if x['event_id']]
    raw=ScopedRecords('records')[os.environ['FIXTURE_REVIEW_ID']]
    print(json.dumps({'status':response.status_code,'body':body,'events':events,
                      'private_code_kept':all('def test_' in t['code'] for t in raw['review']['sealed_tests'])}))
"""
    child_env = {**os.environ, 'FIXTURE_EVIDENCE_ID': evidence_id, 'FIXTURE_REVIEW_ID': review_id}
    child = subprocess.run([sys.executable, '-c', script], cwd=ROOT / 'services/api', env=child_env,
                           capture_output=True, text=True, encoding='utf-8', timeout=20,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert child.returncode == 0, 'fresh API process failed'
    restored = json.loads(child.stdout)
    assert restored['status'] == 200 and restored['private_code_kept']
    assert restored['body']['run']['heldout']['pass'] == 3
    assert restored['events'] and canary not in child.stdout
    assert all('stage' in event and 'summary' in event for event in restored['events'])


def test_durable_evidence_scope_immutability_and_shared_links(funded, durable_api, monkeypatch):
    from evoforge import evidence, postgres_state
    records = postgres_state.ScopedRecords('records')
    records['e1'] = {'id': 'e1', 'gates': []}
    records['e2'] = {'id': 'e2'}
    event = evidence.record('Gate', evidence_id='e1', summary={'result': 'INCONCLUSIVE'})
    for parent in ('e1', 'e2'):
        assert evidence.link(parent, 'Gate', event) == event
        assert evidence.link(parent, 'Gate', event) == event
    assert evidence.view(event)['evidence_ids'] == ['e1', 'e2']
    records['e1'] = {'id': 'e1', 'gates': []}  # exact replay
    with pytest.raises(KernelRejected):
        records['e1'] = {'id': 'e1', 'gates': [{'result': 'PASS'}]}
    with pytest.raises(KernelRejected):
        records.clear()
    other = evidence.record('Gate', evidence_id='e1', summary={})
    with pytest.raises(KernelRejected):
        evidence.link('e1', 'Gate', other)
    monkeypatch.setenv('EVO_PROJECT_ID', str(uuid4()))
    absent = durable_api.get('/v1/evidence/e1')
    missing = durable_api.get('/v1/evidence/missing')
    assert absent.status_code == missing.status_code == 404 and absent.json() == missing.json()
    assert evidence.view(event) is None
    assert len(records) == 0


def test_state_database_failure_prevents_provider_call_without_memory_fallback(funded, durable_api, monkeypatch):
    import main
    from evoforge import commands
    main._evidence._memory['private-memory'] = {'id': 'private-memory'}
    monkeypatch.setenv('DATABASE_URL', 'postgresql://private:never-echo-this@127.0.0.1:1/missing')
    called = []
    monkeypatch.setattr(main.broker_meta, 'call_builder', lambda *args: called.append(args))
    key = 'db-failure-' + uuid4().hex
    response = durable_api.post('/v1/commands/generate', json={'goal': 'must not call provider', 'idempotency_key': key})
    assert response.status_code == 503 and not called
    assert key not in commands._by_key
    read = durable_api.get('/v1/evidence/private-memory')
    assert read.status_code == 503
    assert 'never-echo-this' not in response.text + read.text


def test_unknown_state_backend_is_not_a_memory_mode(funded, durable_api, monkeypatch):
    monkeypatch.setenv('EVO_STATE_BACKEND', 'postgrez')
    assert durable_api.post('/v1/objectives', json={'goal': 'g'}).status_code == 503


@pytest.fixture
def core_runner(funded,durable_api,http_kernel,monkeypatch,tmp_path):
    """Real Runner/Postgres, synthetic Critic+receipt+registered image; no paid calls."""
    import main
    repo=tmp_path/'core-source'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
    git('init','-q')
    git('config','user.name','Fixture')
    git('config','user.email','fixture@example.invalid')
    (repo/'value.py').write_text('result = 2\n',encoding='utf-8')
    git('add','value.py')
    git('commit','-qm','base')
    base=git('rev-parse','HEAD')
    (repo/'value.py').write_text('result = 3\n',encoding='utf-8')
    git('commit','-qam','candidate')
    head=git('rev-parse','HEAD')
    context=_builder_packet(funded,base_sha=base)
    scope=funded['scope']
    candidate,call=uuid4(),uuid4()
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        conn.execute('INSERT INTO core.candidates(tenant_id,project_id,candidate_id,task_id,author_agent_id,base_sha,head_sha) '
                     'VALUES (%s,%s,%s,%s,%s,%s,%s)',(scope.tenant_id,scope.project_id,candidate,context['task'],context['agent'],base,head))
    _prepare(funded,context['packet'],call)
    funded['kernel'].mark_sent(call)
    receipt=receipt_document(tenant=scope.tenant_id,project=scope.project_id,packet=context['packet'],call=call)
    funded['kernel'].record_receipt(receipt)
    assert funded['kernel'].settle_from_receipt(receipt['receipt_id']).status=='COMMITTED'
    monkeypatch.setenv('EVO_RUNNER_IMAGE_DIGEST','sha256:'+'7'*64)
    monkeypatch.setenv('EVO_RUNNER_URL','')
    monkeypatch.setenv('EVO_REPO_ROOTS',str(tmp_path))
    monkeypatch.setenv('EVO_ALLOW_LOCAL_REPOS','1')
    sealed=[{'kind':kind,'code':f'# CORE_SEALED_CANARY_303\nfrom value import result\ndef test_{kind}():\n    assert result == 3\n'}
            for kind in ('compositional','negative','boundary')]
    monkeypatch.setattr(main.broker_meta,'call_critic',lambda *args,**kwargs:{
        'stub':False,'model':'muse-spark-1.3','sealed_tests':sealed,'review':{'result':'PASS'}})
    review=durable_api.post('/v1/candidates/review',json={'goal_contract':'result is 3'})
    assert review.status_code==200,review.text
    request={'source_repo':str(repo),'base_sha':head,'diff':'',
             'tests':[{'code':'from value import result\ndef test_value():\n    assert result == 3\n'}],
             'review_evidence_id':review.json()['evidence_id']}
    response=durable_api.post('/v1/runs',json=request)
    assert response.status_code==200,response.text
    assert response.json()['run']['heldout']['pass']==3
    return {'candidate':candidate,'call':call,'context':context,'head':head,'request':request,
            'evidence':response.json()['evidence_id'],'client':http_kernel,'api':durable_api}


def _bind_core_run(ctx,evidence=None,**extra):
    return ctx['client'].post('/v1/kernel/candidate-runs',json={
        'candidate_id':str(ctx['candidate']),'call_id':str(ctx['call']),
        'evidence_id':evidence or ctx['evidence'],**extra})


def test_actual_runner_gate_is_receipt_and_head_bound_durable_and_cannot_authorize_merge(funded,core_runner):
    from evoforge.postgres_run_evidence import record,read
    ctx=core_runner
    response=_bind_core_run(ctx)
    assert response.status_code==200,response.text
    row=response.json()
    assert row['result']=='PASS' and row['head_sha']==ctx['head']
    assert 'CORE_SEALED_CANARY_303' not in response.text
    assert _bind_core_run(ctx).json()==row
    fresh=PostgresKernel(funded['dsn'],funded['scope'])
    assert read(fresh,ctx['candidate'],ctx['evidence'])['gate_result_id']==UUID(row['gate_result_id'])
    foreign=PostgresKernel(funded['dsn'],KernelScope(funded['scope'].tenant_id,uuid4()))
    with pytest.raises(KernelNotFound):
        read(foreign,ctx['candidate'],ctx['evidence'])
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('DELETE FROM runtime.candidate_run_evidence WHERE candidate_id=%s',(ctx['candidate'],))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE runtime.candidate_run_evidence SET evidence_sha256=repeat('0',64) WHERE candidate_id=%s",
                         (ctx['candidate'],))
    with ThreadPoolExecutor(max_workers=6) as workers:
        ids=list(workers.map(lambda _:record(fresh,ctx['candidate'],ctx['call'],ctx['evidence'])['gate_result_id'],range(6)))
    assert len(set(ids))==1
    with fresh._transaction() as conn:
        gates=conn.execute('SELECT gate,result FROM core.gate_results WHERE candidate_id=%s',(ctx['candidate'],)).fetchall()
        assert gates==[{'gate':'G2_REQUIRED','result':'PASS'}]
        assert conn.execute('SELECT status FROM core.candidates WHERE candidate_id=%s',(ctx['candidate'],)).fetchone()['status']=='PROPOSED'
    denied=ctx['client'].post('/v1/kernel/merge-authorizations',json={
        'candidate_id':str(ctx['candidate']),'head_sha':ctx['head'],'policy_hash':'1'*64})
    assert denied.status_code==409
    child_env={**os.environ,'CORE_CANDIDATE':str(ctx['candidate']),'CORE_EVIDENCE':ctx['evidence']}
    script="""import json,os
import main
from fastapi.testclient import TestClient
with TestClient(main.app) as c:
    r=c.get('/v1/kernel/candidates/'+os.environ['CORE_CANDIDATE']+'/runner-evidence/'+os.environ['CORE_EVIDENCE'],
            headers={'Authorization':'Bearer '+os.environ['EVO_KERNEL_TOKEN']})
    assert r.status_code==200
    print(json.dumps(r.json()))
"""
    child=subprocess.run([sys.executable,'-c',script],cwd=ROOT/'services/api',env=child_env,capture_output=True,
                         text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert child.returncode==0 and __import__('json').loads(child.stdout)['gate_result_id']==row['gate_result_id']


@pytest.mark.parametrize('change',['diff','head','result','image','review'])
def test_runner_gate_rejects_mismatched_server_evidence_without_partial_rows(funded,core_runner,change):
    import main
    from copy import deepcopy
    ctx=core_runner
    document=deepcopy(main._evidence[ctx['evidence']])
    document.pop('id')
    if change=='diff':
        document['diff']='--- a/value.py\n+++ b/value.py\n@@ -1 +1 @@\n-result = 2\n+result = 3\n'
    elif change=='head':
        document['base_sha']='f'*40
    elif change=='result':
        document['run']['visible']['pass']=0
    elif change=='image':
        document['run']['attestation']['runner_image_digest']='sha256:'+'8'*64
    else:
        document['review_evidence_id']=None
    eid=main._store_evidence(document)
    main._link_stages(eid,('Candidate','Gate'))
    assert _bind_core_run(ctx,eid).status_code in (404,409)
    with funded['kernel']._transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM core.gate_results WHERE candidate_id=%s',(ctx['candidate'],)).fetchone()['n']==0
    assert funded['kernel'].reservation(ctx['call']).status=='COMMITTED'


def test_runner_gate_requires_settlement_current_fence_and_server_owned_fields(funded,core_runner,monkeypatch):
    ctx=core_runner
    assert _bind_core_run(ctx,tenant_id=str(uuid4())).status_code==422
    assert _bind_core_run(ctx,result='PASS').status_code==422
    with monkeypatch.context() as patch:
        patch.delenv('EVO_RUNNER_IMAGE_DIGEST')
        assert _bind_core_run(ctx).status_code==503
    pending=uuid4()
    _prepare(funded,ctx['context']['packet'],pending)
    request={'candidate_id':str(ctx['candidate']),'call_id':str(pending),'evidence_id':ctx['evidence']}
    assert ctx['client'].post('/v1/kernel/candidate-runs',json=request).status_code==409
    assert funded['kernel'].reservation(pending).status=='RESERVED'
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        conn.execute('UPDATE core.tasks SET lease_epoch=lease_epoch+1 WHERE task_id=%s',(ctx['context']['task'],))
    assert _bind_core_run(ctx).status_code==409
    monkeypatch.setenv('EVO_PROJECT_ID',str(uuid4()))
    missing=ctx['client'].get(f'/v1/kernel/candidates/{ctx["candidate"]}/runner-evidence/{ctx["evidence"]}')
    unknown=ctx['client'].get(f'/v1/kernel/candidates/{uuid4()}/runner-evidence/missing')
    assert missing.status_code==unknown.status_code==404 and missing.json()==unknown.json()


def test_failed_real_run_records_fail_and_old_success_replay_cannot_override_it(funded,core_runner):
    from copy import deepcopy
    ctx=core_runner
    assert _bind_core_run(ctx).json()['result']=='PASS'
    request=deepcopy(ctx['request'])
    request['tests'][0]['code']=request['tests'][0]['code'].replace('result == 3','result == 4')
    failed=ctx['api'].post('/v1/runs',json=request)
    assert failed.status_code==200 and failed.json()['run']['visible']['pass']==0
    assert _bind_core_run(ctx,failed.json()['evidence_id']).json()['result']=='FAIL'
    assert _bind_core_run(ctx).json()['result']=='PASS'  # historical replay, no new row
    with funded['kernel']._transaction() as conn:
        results=conn.execute('SELECT result FROM core.gate_results WHERE candidate_id=%s ORDER BY recorded_at DESC',
                             (ctx['candidate'],)).fetchall()
        assert results==[{'result':'FAIL'},{'result':'PASS'}]


def test_runner_gate_and_binding_rollback_together_on_storage_failure(funded,core_runner,monkeypatch):
    from evoforge import postgres_run_evidence as bridge
    from evoforge.postgres_kernel import KernelUnavailable
    ctx=core_runner
    original=bridge._read
    called=[]
    def fail_after_writes(*args):
        called.append(True)
        if len(called)==2:
            raise KernelUnavailable('injected storage failure')
        return original(*args)
    monkeypatch.setattr(bridge,'_read',fail_after_writes)
    assert _bind_core_run(ctx).status_code==503
    with funded['kernel']._transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM core.gate_results WHERE candidate_id=%s',(ctx['candidate'],)).fetchone()['n']==0
        assert conn.execute('SELECT count(*) AS n FROM runtime.candidate_run_evidence WHERE candidate_id=%s',(ctx['candidate'],)).fetchone()['n']==0


def test_remote_bundle_runner_provenance_survives_client_and_backstops_core_gate(core_runner,monkeypatch):
    import importlib.util
    import httpx
    from copy import deepcopy
    ctx=core_runner
    spec=importlib.util.spec_from_file_location('codex_runner_wire_fixture',ROOT/'services/runner/app.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from fastapi.testclient import TestClient
    captured=[]
    with TestClient(module.app,raise_server_exceptions=False) as service:
        def send(url,**kwargs):
            assert url=='https://runner.test.invalid/run'
            response=service.post('/run',json=kwargs['json'])
            captured.append(response.json())
            return response
        monkeypatch.setenv('EVO_RUNNER_URL','https://runner.test.invalid')
        monkeypatch.setenv('EVO_RUNNER_AUDIENCE','')
        monkeypatch.setattr(httpx,'post',send)
        response=ctx['api'].post('/v1/runs',json=ctx['request'])
    assert response.status_code==200,response.text
    assert captured and response.json()['run']['attestation']['runner_image_digest']=='sha256:'+'7'*64
    assert _bind_core_run(ctx,response.json()['evidence_id']).json()['result']=='PASS'
    assert 'CORE_SEALED_CANARY_303' not in response.text
    # The API client validates the configured identity and counts before a
    # malformed Runner response can become a persisted gate/evidence record.
    for change in ('counts','attestation'):
        raw=deepcopy(captured[0])
        if change=='counts':
            raw['visible']['pass']=raw['visible']['n']+1
        else:
            raw.pop('attestation')
        monkeypatch.setattr(httpx,'post',lambda *args,**kwargs:httpx.Response(200,json=raw))
        assert ctx['api'].post('/v1/runs',json=ctx['request']).status_code==502


@pytest.fixture
def command_store(funded, monkeypatch):
    from evoforge.postgres_commands import CommandStore
    monkeypatch.setenv('EVO_COMMAND_ACTOR_ID', str(uuid4()))
    return CommandStore(funded['kernel'])


def _command_response_evidence(funded, response):
    from evoforge.postgres_state import EvidenceStore
    eid=response['evidence']['id']
    document={'id':eid,'command_id':response['command_id'],
              **{key:response[key] for key in ('candidate','gates') if key in response}}
    EvidenceStore(funded['kernel']).write('records',eid,document)
    return response


def test_canonical_command_response_and_history_survive_new_store_and_process(funded, command_store):
    from evoforge.postgres_commands import CommandStore
    created = command_store.create('한글 goal', 'arbitrary / key with spaces')
    cid = created['command_id']
    assert created['state'] == 'RECEIVED' and created['kind'] == 'BUILD'
    dispatched = command_store.dispatch(cid)
    assert dispatched['state'] == 'DISPATCHED'
    body = {'command_id': cid, 'candidate': {'diff': 'verified fixture'}, 'evidence': {'id': 'ev_fixture'}}
    _command_response_evidence(funded,body)
    dispatched['served'] = body
    assert dispatched['state'] == 'APPLIED'
    restarted = CommandStore(funded['kernel']).create('한글 goal', 'arbitrary / key with spaces')
    assert restarted['served'] == body
    assert [state for state, _ in restarted['history']] == ['RECEIVED','VALIDATING','PLANNED','DISPATCHED','APPLYING','APPLIED']
    with psycopg.connect(funded['dsn']) as conn:
        row = conn.execute('SELECT kind,status,payload FROM core.commands WHERE command_id=%s', (UUID(cid[4:]),)).fetchone()
        assert row[0:2] == ('ASK','APPLIED') and row[2]['api_kind'] == 'BUILD'
    env = {**os.environ, 'COMMAND_CHECK_DSN': funded['dsn'], 'COMMAND_CHECK_TENANT': str(funded['scope'].tenant_id),
           'COMMAND_CHECK_PROJECT': str(funded['scope'].project_id), 'COMMAND_CHECK_ID': cid}
    script = """import os
from evoforge.postgres_kernel import KernelScope,PostgresKernel
from evoforge.postgres_commands import CommandStore
s=CommandStore(PostgresKernel(os.environ['COMMAND_CHECK_DSN'],KernelScope(os.environ['COMMAND_CHECK_TENANT'],os.environ['COMMAND_CHECK_PROJECT'])))
r=s.get(os.environ['COMMAND_CHECK_ID'])
assert r['state']=='APPLIED' and r['served']['evidence']['id']=='ev_fixture'
print('restored')
"""
    child = subprocess.run([sys.executable,'-c',script],cwd=ROOT/'services/api',env=env,capture_output=True,
                           text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert child.returncode == 0 and child.stdout.strip() == 'restored'


def test_command_retry_after_dispatch_never_authorizes_another_attempt(funded, command_store):
    from evoforge.commands import TransitionError
    from evoforge.postgres_commands import CommandStore
    cid = command_store.create('g','call-key')['command_id']
    command_store.dispatch(cid)
    restarted = CommandStore(funded['kernel'])
    assert restarted.create('g','call-key')['state'] == 'DISPATCHED'
    with pytest.raises(TransitionError):
        restarted.dispatch(cid)
    with pytest.raises(TransitionError):
        restarted.advance(cid,'APPLIED')  # client status input cannot fabricate completion
    assert 'served' not in restarted.get(cid)


def test_concurrent_command_acceptance_and_dispatch_are_single_flight(command_store):
    from evoforge.commands import TransitionError
    with ThreadPoolExecutor(max_workers=6) as workers:
        rows = list(workers.map(lambda _: command_store.create('g','concurrent-key'),range(6)))
    assert len({row['command_id'] for row in rows}) == 1
    def dispatch(_):
        try:
            command_store.dispatch(rows[0]['command_id'])
            return True
        except TransitionError:
            return False
    with ThreadPoolExecutor(max_workers=6) as workers:
        assert sum(workers.map(dispatch,range(6))) == 1


def test_canonical_command_refuses_changed_replay_invalid_transitions_and_risky_shortcuts(command_store):
    from evoforge.commands import NeedsConfirmation, TransitionError
    first = command_store.create('g','unique-key')
    with pytest.raises(TransitionError):
        command_store.create('different goal','unique-key')
    with pytest.raises(TransitionError):
        command_store.advance(first['command_id'],'APPLIED')
    assert command_store.get(first['command_id'])['state'] == 'RECEIVED'
    with pytest.raises(NeedsConfirmation):
        command_store.create('risk','high-risk',risk='HIGH')
    with pytest.raises(TransitionError):
        command_store.create('merge','merge-key',kind='APPROVE_MERGE',confirm=True)


def test_canonical_command_versions_and_safety_fast_lane_are_db_enforced(command_store):
    from evoforge.commands import TransitionError
    with pytest.raises(TransitionError):
        command_store.create('stale','stale-key',expected_version='999')
    stop = command_store.create('stop','stop-key',kind='STOP_ALL',expected_version='999')
    assert stop['kind'] == 'STOP_ALL'


def test_command_results_are_immutable_and_commands_are_scope_isolated(funded, command_store):
    from evoforge.commands import TransitionError
    from evoforge.postgres_commands import CommandStore
    cmd = command_store.create('g','result-key')
    command_store.dispatch(cmd['command_id'])
    result = _command_response_evidence(funded,{'command_id':cmd['command_id'],'candidate':{'diff':'x'},
                                                'evidence':{'id':'ev_result'}})
    command_store.complete(cmd['command_id'],result)
    assert command_store.complete(cmd['command_id'],result)['served'] == result
    with pytest.raises(TransitionError):
        command_store.complete(cmd['command_id'],{**result,'candidate': {'diff':'changed'}})
    foreign = CommandStore(PostgresKernel(funded['dsn'],KernelScope(funded['scope'].tenant_id,uuid4())))
    assert foreign.get(cmd['command_id']) is None


def test_command_input_errors_do_not_accept_or_confirm_a_command(funded, command_store, monkeypatch):
    from decimal import Decimal
    from evoforge.commands import TransitionError
    from evoforge.postgres_kernel import KernelUnavailable
    for version in (True, 1.0, Decimal(0), '01', -1, 2**63):
        with pytest.raises(TransitionError):
            command_store.create('g', 'bad-version', expected_version=version)
    for goal, key, options in [('g', 'bad-confirm', {'risk':'HIGH', 'confirm':'false'}),
                               ('nul\x00goal', 'bad-text', {}),
                               ('g', 'nul\x00key', {}), ('surrogate\ud800', 'bad-text', {})]:
        with pytest.raises(TransitionError):
            command_store.create(goal, key, **options)
    monkeypatch.delenv('EVO_COMMAND_ACTOR_ID')
    with pytest.raises(KernelUnavailable, match='actor is not configured'):
        command_store.create('g', 'missing-actor')
    with funded['kernel']._transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM core.commands WHERE tenant_id=%s AND project_id=%s',
                            command_store.scope).fetchone()['n'] == 0


def test_database_refuses_responses_for_unapplied_or_mismatched_commands(funded, command_store):
    cmd = command_store.create('g', 'response-constraints')
    cid = UUID(cmd['command_id'][4:])
    def insert(document):
        with funded['kernel']._transaction() as conn:
            conn.execute('INSERT INTO runtime.api_command_results(tenant_id,project_id,command_id,document) '
                         'VALUES (%s,%s,%s,%s)', (*command_store.scope,cid,Jsonb(document)))
    result=_command_response_evidence(funded,{'command_id':cmd['command_id'],'candidate':{'diff':'stored'},
                                             'gates':[{'gate':'GH_INTEGRITY','result':'INCONCLUSIVE'}],
                                             'evidence':{'id':'ev_response_constraints'}})
    with pytest.raises(KernelRejected):
        insert(result)  # RECEIVED is not complete
    command_store.dispatch(cmd['command_id'])
    # Even a direct application SQL update cannot commit false completion.
    with pytest.raises(KernelRejected):
        with funded['kernel']._transaction() as conn:
            conn.execute("UPDATE core.commands SET status='APPLIED' WHERE command_id=%s", (cid,))
    assert command_store.get(cmd['command_id'])['state']=='DISPATCHED'
    # A trusted controller must save the matching result in that transaction.
    with funded['kernel']._transaction() as conn:
        conn.execute("UPDATE core.commands SET status='APPLIED' WHERE command_id=%s", (cid,))
        for document in ({}, {'command_id':'cmd_'+uuid4().hex},
                         {**result,'evidence':{'id':'missing'}},
                         {**result,'candidate':{'diff':'forged'}},
                         {**result,'gates':[{'gate':'GH_INTEGRITY','result':'PASS'}]}):
            with pytest.raises(psycopg.errors.CheckViolation):
                with conn.transaction():  # savepoint keeps the completion transaction usable
                    conn.execute('INSERT INTO runtime.api_command_results(tenant_id,project_id,command_id,document) '
                                 'VALUES (%s,%s,%s,%s)', (*command_store.scope,cid,Jsonb(document)))
        conn.execute('INSERT INTO runtime.api_command_results(tenant_id,project_id,command_id,document) '
                     'VALUES (%s,%s,%s,%s)', (*command_store.scope,cid,Jsonb(result)))
    with funded['kernel']._transaction() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('UPDATE runtime.api_command_results SET document=%s WHERE command_id=%s',
                         (Jsonb({'command_id':cmd['command_id'],'changed':True}),cid))


def test_command_status_read_does_not_mix_states_across_completion(funded, command_store, monkeypatch):
    from threading import Event
    cmd = command_store.create('g','consistent-status')
    command_store.dispatch(cmd['command_id'])
    response=_command_response_evidence(funded,{'command_id':cmd['command_id'],'evidence':{'id':'ev_consistent'}})
    entered, release = Event(), Event()
    original = command_store._view
    def pause_view(conn,row):
        if row['status'] == 'DISPATCHED':
            entered.set()
            assert release.wait(10), 'status read did not resume'
        return original(conn,row)
    monkeypatch.setattr(command_store,'_view',pause_view)
    with ThreadPoolExecutor(max_workers=2) as workers:
        reading = workers.submit(command_store.get,cmd['command_id'])
        assert entered.wait(5)
        completing = workers.submit(command_store.complete,cmd['command_id'],response)
        try:
            with psycopg.connect(funded['dsn'],autocommit=True) as control:
                deadline = time.monotonic()+5
                while time.monotonic() < deadline:
                    # Row writers wait on a transaction-ID lock, whose own
                    # pg_locks.database is NULL; scope via the waiting session.
                    waiting = control.execute('SELECT EXISTS(SELECT 1 FROM pg_locks l '
                                              'JOIN pg_stat_activity a USING(pid) WHERE NOT l.granted '
                                              'AND a.datname=current_database())').fetchone()[0]
                    if waiting:
                        break
                    time.sleep(0.01)
                assert waiting, 'completion must wait for the status snapshot'
        finally:
            release.set()
        old = reading.result(timeout=10)
        new = completing.result(timeout=10)
    assert old['state'] == 'DISPATCHED' and 'served' not in old
    assert [state for state,_ in old['history']][-1] == 'DISPATCHED'
    assert new['state'] == 'APPLIED' and new['served']['command_id'] == cmd['command_id']


def test_command_completion_failure_rolls_back_state_history_and_response(funded,command_store, monkeypatch):
    from evoforge.postgres_kernel import KernelUnavailable
    cmd = command_store.create('g','completion-rollback')
    command_store.dispatch(cmd['command_id'])
    response=_command_response_evidence(funded,{'command_id':cmd['command_id'],'evidence':{'id':'ev_rollback'}})
    def fail_after_insert(*args):
        raise KernelUnavailable('injected failure')
    with monkeypatch.context() as patch:
        patch.setattr(command_store,'_view',fail_after_insert)
        with pytest.raises(KernelUnavailable):
            command_store.complete(cmd['command_id'],response)
    row = command_store.get(cmd['command_id'])
    assert row['state']=='DISPATCHED' and 'served' not in row
    assert [state for state,_ in row['history']] == ['RECEIVED','VALIDATING','PLANNED','DISPATCHED']
    # Completion can safely reuse the existing proof after recovery; dispatch
    # remains single-flight and no provider invocation is needed.
    assert command_store.complete(cmd['command_id'],response)['state']=='APPLIED'


def test_command_completion_rejects_missing_other_command_and_foreign_evidence(funded,command_store):
    from evoforge.commands import TransitionError
    from evoforge.postgres_state import EvidenceStore
    first=command_store.create('g','first-response')
    second=command_store.create('other','second-response')
    cid=first['command_id']
    command_store.dispatch(cid)
    evidence=_command_response_evidence(funded,{'command_id':second['command_id'],'evidence':{'id':'ev_other_command'}})
    for body in ({'command_id':cid}, {'command_id':cid,'evidence':{'id':'missing'}},
                 {**evidence,'command_id':cid}):
        with pytest.raises(TransitionError):
            command_store.complete(cid,body)
    project=uuid4()
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        conn.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'foreign')",
                     (funded['scope'].tenant_id,project))
    foreign=PostgresKernel(funded['dsn'],KernelScope(funded['scope'].tenant_id,project))
    EvidenceStore(foreign).write('records','ev_foreign',{'id':'ev_foreign','command_id':cid})
    with pytest.raises(TransitionError):
        command_store.complete(cid,{'command_id':cid,'evidence':{'id':'ev_foreign'}})
    remaining=command_store.get(cid)
    assert remaining['state']=='DISPATCHED' and 'served' not in remaining
    assert [state for state,_ in remaining['history']][-1]=='DISPATCHED'


def test_http_canonical_command_lifecycle_persists_once_across_new_api_process(funded,http_kernel,monkeypatch):
    monkeypatch.setenv('EVO_COMMAND_ACTOR_ID',str(uuid4()))
    request={'goal':'verified command fixture','idempotency_key':'http-command','risk':'HIGH','confirm':True}
    refused=http_kernel.post('/v1/kernel/commands',json={**request,'confirm':False})
    assert refused.status_code==409
    replies=[http_kernel.post('/v1/kernel/commands',json=request) for _ in range(20)]
    assert all(r.status_code==200 for r in replies)
    assert len({r.json()['command_id'] for r in replies})==1
    cid=replies[0].json()['command_id']
    path='/v1/kernel/commands/'+cid
    assert http_kernel.post(path+'/dispatch',json={}).json()['state']=='DISPATCHED'
    assert http_kernel.post(path+'/dispatch',json={}).status_code==409
    response=_command_response_evidence(funded,{'command_id':cid,'candidate':{'diff':'fixture'},
                                               'gates':[{'gate':'GH_INTEGRITY','result':'INCONCLUSIVE'}],
                                               'evidence':{'id':'ev_http_command'}})
    wrong={**response,'gates':[{'gate':'GH_INTEGRITY','result':'PASS'}]}
    assert http_kernel.post(path+'/complete',json={'response':wrong}).status_code==409
    applied=http_kernel.post(path+'/complete',json={'response':response})
    assert applied.status_code==200 and applied.json()['state']=='APPLIED'
    assert applied.json()['served']==response and '_store' not in applied.text
    assert http_kernel.post(path+'/complete',json={'response':response}).json()==applied.json()
    script="""import os
import main
from fastapi.testclient import TestClient
with TestClient(main.app) as c:
    r=c.get('/v1/kernel/commands/'+os.environ['CHECK_COMMAND_ID'],
            headers={'Authorization':'Bearer '+os.environ['EVO_KERNEL_TOKEN']})
    assert r.status_code==200 and r.json()['state']=='APPLIED'
    assert r.json()['served']['evidence']['id']=='ev_http_command'
    print('restored')
"""
    child=subprocess.run([sys.executable,'-c',script],cwd=ROOT/'services/api',
                         env={**os.environ,'CHECK_COMMAND_ID':cid},capture_output=True,text=True,timeout=20,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert child.returncode==0 and child.stdout.strip()=='restored'


def test_http_commands_are_scoped_and_missing_actor_never_falls_back_to_memory(funded,http_kernel,monkeypatch):
    from evoforge import commands
    request={'goal':'g','idempotency_key':'http-missing-actor'}
    monkeypatch.delenv('EVO_COMMAND_ACTOR_ID',raising=False)
    assert http_kernel.post('/v1/kernel/commands',json=request).status_code==503
    assert request['idempotency_key'] not in commands._by_key
    monkeypatch.setenv('EVO_COMMAND_ACTOR_ID',str(uuid4()))
    cid=http_kernel.post('/v1/kernel/commands',json=request).json()['command_id']
    monkeypatch.setitem(commands._by_id,cid,{'command_id':cid,'state':'APPLIED','served':{'private':'memory'}})
    monkeypatch.setenv('EVO_PROJECT_ID',str(uuid4()))
    read=http_kernel.get('/v1/kernel/commands/'+cid)
    absent=http_kernel.get('/v1/kernel/commands/cmd_'+uuid4().hex)
    assert read.status_code==absent.status_code==404 and read.json()==absent.json()
    assert http_kernel.post('/v1/kernel/commands/'+cid+'/dispatch',json={}).status_code==404


def test_http_command_inputs_do_not_grant_approval_or_accept_loose_confirmation(http_kernel,monkeypatch):
    monkeypatch.setenv('EVO_COMMAND_ACTOR_ID',str(uuid4()))
    request={'goal':'g','idempotency_key':'strict-http-command'}
    for invalid in ({'confirm':'true'},{'expected_version':True},{'expected_version':1.5},
                    {'kind':'APPROVE_MERGE'},{'actor_user_id':str(uuid4())},{'tenant_id':str(uuid4())}):
        assert http_kernel.post('/v1/kernel/commands',json={**request,**invalid}).status_code==422
    cid=http_kernel.post('/v1/kernel/commands',json=request).json()['command_id']
    assert http_kernel.post('/v1/kernel/commands/'+cid+'/dispatch',json={'to_state':'APPLIED'}).status_code==422
    assert http_kernel.post('/v1/kernel/commands/'+cid+'/complete',json={
        'response':{'command_id':cid,'evidence':{'id':'missing'}}}).status_code==409


def test_deferred_command_completion_works_with_session_role_and_rls(funded,command_store):
    from evoforge.postgres_commands import CommandStore
    # The session remains core_app when SET LOCAL ROLE unwinds, so deferred
    # checks cannot accidentally rely on the test administrator's RLS bypass.
    dsn=make_conninfo(funded['dsn'],options='-c role=core_app')
    restricted=CommandStore(PostgresKernel(dsn,funded['scope']))
    cid=restricted.create('strict role','strict-role-completion')['command_id']
    restricted.dispatch(cid)
    response=_command_response_evidence(funded,{'command_id':cid,'evidence':{'id':'ev_strict_role'}})
    assert restricted.complete(cid,response)['state']=='APPLIED'
    assert restricted.get(cid)['served']==response


def test_real_database_command_accepts_separate_google_and_kernel_credentials(http_kernel,monkeypatch):
    import main
    audience='https://db-api.test.invalid'
    service='approved@test.invalid'
    monkeypatch.setenv('EVO_COMMAND_ACTOR_ID',str(uuid4()))
    monkeypatch.setenv('EVO_REQUIRE_ID_TOKEN','1')
    monkeypatch.setenv('EVO_API_URL',audience)
    monkeypatch.setenv('EVO_WEB_SERVICE_ACCOUNT',service)
    def identity(token,expected):
        if token!='trusted-test-id' or expected!=audience:
            raise ValueError('invalid ID token')
        return {'aud':audience,'email':service}
    monkeypatch.setattr(main.auth_module,'verify_id_token',identity)
    headers={'Authorization':'Bearer trusted-test-id',
             'X-Evoforge-Kernel-Token':'test-only-live-kernel-token-not-a-real-secret'}
    request={'goal':'two independent auth gates','idempotency_key':'dual-auth-command'}
    assert http_kernel.post('/v1/kernel/commands',json=request,headers={
        'Authorization':headers['Authorization']}).status_code==401
    accepted=http_kernel.post('/v1/kernel/commands',json=request,headers=headers)
    assert accepted.status_code==200,accepted.text
    cid=accepted.json()['command_id']
    assert http_kernel.get('/v1/kernel/commands/'+cid,headers=headers).json()['state']=='RECEIVED'


def _mission_output(mid,*,linked=True,label='one'):
    import main
    eid=main._store_evidence({'mission_id':mid,'candidate':{'diff':label,'tests':[]},
                              'gates':[{'gate':'GH_INTEGRITY','result':'INCONCLUSIVE'}]})
    if linked:
        main._link_stages(eid,('Task','Candidate','Gate'))
    return eid


def test_public_mission_generation_survives_new_api_process_and_updates_live_view(funded,durable_api,monkeypatch):
    import main
    from evoforge import missions
    calls=[]
    def builder(*args,**kwargs):
        calls.append(True)
        return {'diff':'','tests':[{'code':'def test_fixture():\n    assert 2 + 2 == 4\n'}],
                'model':'muse-spark-1.3','stub':False}
    monkeypatch.setattr(main.broker_meta,'call_builder',builder)
    created=durable_api.post('/v1/missions',json={'goal':'durable fixture','repo_ref':'a'*40})
    assert created.status_code==201,created.text
    mid=created.json()['mission_id']
    live=missions.get(mid)
    generated=durable_api.post(f'/v1/missions/{mid}/advance',json={'to':'GENERATED'})
    assert generated.status_code==200,generated.text
    eid=generated.json()['evidence_id']
    assert calls==[True] and eid in generated.json()['evidence_ids']
    assert live['state']=='GENERATED' and live['stages']['generate']==eid
    assert durable_api.get('/v1/dashboard').json()['missions_by_state']['GENERATED']==1
    script="""import json,os
import main
from fastapi.testclient import TestClient
with TestClient(main.app) as c:
    r=c.get('/v1/missions/'+os.environ['CHECK_MISSION_ID'])
    assert r.status_code==200
    body=r.json()
    assert body['state']=='GENERATED' and body['generate_evidence_id']==os.environ['CHECK_MISSION_EVIDENCE']
    assert c.get('/v1/dashboard').json()['active_missions']==1
    print(json.dumps(body))
"""
    child=subprocess.run([sys.executable,'-c',script],cwd=ROOT/'services/api',
                         env={**os.environ,'CHECK_MISSION_ID':mid,'CHECK_MISSION_EVIDENCE':eid},
                         capture_output=True,text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert child.returncode==0 and '_version' not in child.stdout
    assert durable_api.post(f'/v1/missions/{mid}/advance',json={'to':'GENERATED'}).status_code==409
    assert calls==[True]


def test_mission_recovery_adopts_committed_output_without_sending_builder(funded,durable_api,monkeypatch):
    import main
    from evoforge import missions
    mid=durable_api.post('/v1/missions',json={'goal':'recover','repo_ref':'a'*40}).json()['mission_id']
    eid=_mission_output(mid)
    called=[]
    monkeypatch.setattr(main.broker_meta,'call_builder',lambda *a,**k:called.append(True))
    restored=durable_api.get('/v1/missions/'+mid)
    assert restored.status_code==200 and restored.json()['state']=='GENERATED'
    assert restored.json()['generate_evidence_id']==eid and not called
    assert durable_api.post(f'/v1/missions/{mid}/advance',json={'to':'GENERATED'}).status_code==409
    assert not called and missions.get(mid)['state']=='GENERATED'


def test_mission_partial_output_blocks_redispatch_until_event_evidence_is_ready(durable_api,monkeypatch):
    import main
    mid=durable_api.post('/v1/missions',json={'goal':'partial','repo_ref':'a'*40}).json()['mission_id']
    eid=_mission_output(mid,linked=False)
    called=[]
    monkeypatch.setattr(main.broker_meta,'call_builder',lambda *a,**k:called.append(True))
    assert durable_api.get('/v1/missions/'+mid).status_code==409
    assert durable_api.post(f'/v1/missions/{mid}/advance',json={'to':'GENERATED'}).status_code==409
    assert not called
    main._link_stages(eid,('Task','Candidate','Gate'))
    assert durable_api.get('/v1/missions/'+mid).json()['state']=='GENERATED'


def test_multiple_unclaimed_mission_outputs_require_reconciliation(durable_api,monkeypatch):
    import main
    mid=durable_api.post('/v1/missions',json={'goal':'ambiguous','repo_ref':'a'*40}).json()['mission_id']
    _mission_output(mid,label='first')
    _mission_output(mid,label='second')
    called=[]
    monkeypatch.setattr(main.broker_meta,'call_builder',lambda *a,**k:called.append(True))
    assert durable_api.get('/v1/missions/'+mid).status_code==409
    assert durable_api.post(f'/v1/missions/{mid}/advance',json={'to':'GENERATED'}).status_code==409
    assert not called


def test_mission_versions_cannot_fake_progress_change_inputs_or_erase_evidence(funded,durable_api):
    from copy import deepcopy
    from evoforge import missions
    mid=durable_api.post('/v1/missions',json={'goal':'immutable','repo_ref':'a'*40}).json()['mission_id']
    scope=(funded['scope'].tenant_id,funded['scope'].project_id)
    with funded['kernel']._transaction() as conn:
        row=conn.execute('SELECT version,document FROM runtime.api_mission_versions '
                         'WHERE tenant_id=%s AND project_id=%s AND mission_id=%s ORDER BY version DESC LIMIT 1',
                         (*scope,mid)).fetchone()
    for change in ('state','goal','evidence'):
        document=deepcopy(row['document'])
        if change=='state':
            document['state']='GENERATED'
        elif change=='goal':
            document['goal']='replaced'
        else:
            document['evidence_ids']=[]
        with pytest.raises(KernelRejected):
            with funded['kernel']._transaction() as conn:
                conn.execute('INSERT INTO runtime.api_mission_versions(tenant_id,project_id,mission_id,version,document) '
                             'VALUES (%s,%s,%s,%s,%s)',(*scope,mid,row['version']+1,Jsonb(document)))
    with pytest.raises(KernelRejected):
        missions.mark(mid,'GENERATED')
    with pytest.raises(KernelRejected):
        missions.reset()
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('DELETE FROM runtime.api_mission_versions WHERE mission_id=%s',(mid,))
    assert missions.get(mid)['state']=='CREATED'


def test_mission_scope_and_foreign_evidence_do_not_fall_back_to_memory(funded,durable_api,monkeypatch):
    from evoforge import missions
    created=[durable_api.post('/v1/missions',json={'goal':g,'repo_ref':'a'*40}).json()['mission_id'] for g in ('a','b')]
    eid=_mission_output(created[1])
    with pytest.raises(KernelRejected):
        missions.attach_evidence(created[0],eid,'generate')
    monkeypatch.setitem(missions._missions,created[0],{'mission_id':created[0],'private':'memory-canary'})
    monkeypatch.setenv('EVO_PROJECT_ID',str(uuid4()))
    found=durable_api.get('/v1/missions/'+created[0])
    absent=durable_api.get('/v1/missions/msn_missing')
    assert found.status_code==absent.status_code==404 and found.json()==absent.json()
    assert durable_api.get('/v1/missions').json()['missions']==[]


def test_cancelled_mission_keeps_evidence_and_is_not_recovered_forward(durable_api):
    from evoforge import missions
    mid=durable_api.post('/v1/missions',json={'goal':'cancel','repo_ref':'a'*40}).json()['mission_id']
    before=missions.get(mid)
    ids=list(before['evidence_ids'])
    assert durable_api.post(f'/v1/missions/{mid}/cancel').status_code==200
    _mission_output(mid)
    after=durable_api.get('/v1/missions/'+mid).json()
    assert after['state']=='CANCELLED' and after['evidence_ids']==ids
    assert durable_api.post(f'/v1/missions/{mid}/advance',json={'to':'GENERATED'}).status_code==409


def test_mission_database_failure_never_creates_a_process_local_mission(durable_api,monkeypatch):
    from evoforge import missions
    monkeypatch.setenv('DATABASE_URL','postgresql://private:never-echo-mission-secret@127.0.0.1:1/missing')
    existing=set(missions._missions)
    response=durable_api.post('/v1/missions',json={'goal':'no fallback','repo_ref':'a'*40})
    assert response.status_code==503 and 'never-echo-mission-secret' not in response.text
    assert set(missions._missions)==existing


def test_mission_review_real_runner_and_mock_pr_persist_with_sealed_code_private(durable_api,monkeypatch,tmp_path):
    """Real Runner and DB; explicitly synthetic Builder/Critic/GitHub transports."""
    import main
    from evoforge import repo_source,github
    repo=tmp_path/'mission-code'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
    git('init','-q')
    git('config','user.name','Fixture')
    git('config','user.email','fixture@example.invalid')
    (repo/'calc.py').write_text('def add(a, b):\n    return a - b\n',encoding='utf-8')
    git('add','calc.py')
    git('commit','-qm','base')
    base=git('rev-parse','HEAD')
    diff='--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n'
    visible='from calc import add\ndef f_ref(a, b):\n    return a + b\ndef test_sum():\n    assert add(2, 3) == f_ref(2, 3)\n'
    sealed=[{'kind':kind,'code':f'# MISSION_PRIVATE_CANARY_509\nfrom calc import add\ndef test_{kind}():\n    assert add(2, 3) == 5\n'}
            for kind in ('compositional','negative','boundary')]
    monkeypatch.setattr(main.broker_meta,'call_builder',lambda *a,**k:{'diff':diff,'tests':[{'code':visible}],
                         'model':'muse-spark-1.3','stub':False})
    monkeypatch.setattr(main.broker_meta,'call_critic',lambda *a,**k:{'sealed_tests':sealed,'review':{'result':'PASS'},
                         'model':'muse-spark-1.3','stub':False})
    clones=[]
    def clone(source,ref):
        assert source=='' and ref==base
        target=tmp_path/f'resolved-{len(clones)}'
        subprocess.check_call(['git','clone','-q','--no-hardlinks',str(repo),str(target)])
        clones.append(target)
        return str(target)
    monkeypatch.setattr(repo_source,'resolve_repo_dir',clone)
    monkeypatch.setenv('EVO_REPO_ROOTS',str(tmp_path))
    monkeypatch.setenv('EVO_ALLOW_LOCAL_REPOS','1')
    monkeypatch.setenv('EVO_RUNNER_URL','')
    monkeypatch.setattr(github,'create_pr',lambda *a,**k:{'html_url':'https://fixture.invalid/pr/1'})
    created=durable_api.post('/v1/missions',json={'goal':'sum the arguments','repo_ref':base})
    assert created.status_code==201,created.text
    mid=created.json()['mission_id']
    for state in ('GENERATED','REVIEWED','RAN','PR_OPENED'):
        response=durable_api.post(f'/v1/missions/{mid}/advance',json={'to':state})
        assert response.status_code==200,response.text
        assert 'MISSION_PRIVATE_CANARY_509' not in response.text
    detail=durable_api.get('/v1/missions/'+mid).json()
    assert detail['state']=='PR_OPENED' and detail['pr_url']=='https://fixture.invalid/pr/1'
    run=durable_api.get('/v1/evidence/'+detail['run_evidence_id'])
    assert run.json()['run']['visible']['pass']==1 and run.json()['run']['heldout']['pass']==3
    review=durable_api.get('/v1/evidence/'+detail['review_evidence_id'])
    assert 'MISSION_PRIVATE_CANARY_509' not in review.text
    assert clones and all(not target.exists() for target in clones)


def test_mission_confirmation_and_parallel_completion_preserve_one_version_per_change(funded,durable_api):
    from evoforge import missions
    request={'goal':'confirmed fixture','repo_ref':'a'*40,'risk':'HIGH'}
    assert durable_api.post('/v1/missions',json=request).status_code==409
    assert durable_api.get('/v1/missions').json()['missions']==[]
    created=durable_api.post('/v1/missions',json={**request,'confirm':True})
    assert created.status_code==201,created.text
    mid=created.json()['mission_id']
    live=missions.get(mid)
    assert live['confirmed'] is True and live['risk']=='HIGH'
    eid=_mission_output(mid)
    with ThreadPoolExecutor(max_workers=6) as workers:
        list(workers.map(lambda _:missions.attach_evidence(mid,eid,'generate'),range(12)))
        list(workers.map(lambda _:missions.mark(mid,'GENERATED'),range(12)))
    assert live['state']=='GENERATED' and live['evidence_ids'].count(eid)==1
    with funded['kernel']._transaction() as conn:
        versions=conn.execute('SELECT version FROM runtime.api_mission_versions '
                              'WHERE tenant_id=%s AND project_id=%s AND mission_id=%s ORDER BY version',
                              (funded['scope'].tenant_id,funded['scope'].project_id,mid)).fetchall()
    assert [r['version'] for r in versions]==[1,2,3,4]


def test_mission_live_views_never_mix_database_connections():
    from types import SimpleNamespace
    from evoforge.postgres_missions import view
    scope=KernelScope(uuid4(),uuid4())
    def store(name):
        return SimpleNamespace(kernel=PostgresKernel('postgresql://fixture.invalid/'+name,scope),
                               scope=(scope.tenant_id,scope.project_id))
    first=store('first')
    current={'version':9,'document':{'mission_id':'msn_same','goal':'first','state':'GENERATED'}}
    live=view(first,current)
    other=view(store('second'),{'version':1,'document':{**current['document'],'goal':'second','state':'CREATED'}})
    assert other is not live and other['goal']=='second' and live['goal']=='first'
    assert view(first,{'version':8,'document':{**current['document'],'state':'CREATED'}})['state']=='GENERATED'


def _generated_mission(client):
    mid=client.post('/v1/missions',json={'goal':'review recovery','repo_ref':'a'*40}).json()['mission_id']
    _mission_output(mid)
    assert client.get('/v1/missions/'+mid).json()['state']=='GENERATED'
    return mid


def _critic_call_output(phase,**extra):
    import main
    return main._store_evidence({'kind':'provider_call','phase':phase,'metadata':None,
                                 'reservation':{'state':'SETTLED'},'response_document':None,**extra})


def _mission_review_output(mid,phase_ids):
    import main
    review={'stub':False,'model':'muse-spark-1.3','sealed_tests':[
        {'kind':kind,'code':'# RECOVERY_SEALED_PRIVATE_811\ndef test_sealed():\n    assert 2 == 2\n'}
        for kind in ('compositional','negative','boundary')]}
    eid=main._store_evidence({'mission_id':mid,'review':review,'provider_evidence_ids':phase_ids})
    main._link_stages(eid,('Review',))
    return eid


@pytest.mark.parametrize('phase_count',[1,2])
def test_mission_review_recovery_restores_call_evidence_ids_without_resending(durable_api,monkeypatch,phase_count):
    import main
    from evoforge import missions
    mid=_generated_mission(durable_api)
    before=list(missions.get(mid)['evidence_ids'])
    phases=[_critic_call_output(p) for p in ('critic_spec','critic_review')[:phase_count]]
    eid=_mission_review_output(mid,phases)
    calls=[]
    monkeypatch.setattr(main.broker_meta,'call_critic',lambda *a,**k:calls.append(True))
    result=durable_api.get('/v1/missions/'+mid)
    assert result.status_code==200,result.text
    assert result.json()['state']=='REVIEWED' and result.json()['review_evidence_id']==eid
    assert result.json()['evidence_ids']==before+phases+[eid]
    assert 'RECOVERY_SEALED_PRIVATE_811' not in result.text
    assert durable_api.post(f'/v1/missions/{mid}/advance',json={'to':'REVIEWED'}).status_code==409
    assert not calls
    again=missions.get(mid)
    assert again['evidence_ids']==before+phases+[eid]


def test_mission_review_recovery_finishes_partial_call_attachment_atomically(durable_api):
    from evoforge import missions
    mid=_generated_mission(durable_api)
    phases=[_critic_call_output(p) for p in ('critic_spec','critic_review')]
    eid=_mission_review_output(mid,phases)
    missions.attach_evidence(mid,phases[0])
    # Simulates an API exit between the provider-attachment loop's two writes.
    result=missions.attach_evidence(mid,eid,'review')
    assert all(result['evidence_ids'].count(p)==1 for p in phases+[eid])
    missions.mark(mid,'REVIEWED')
    assert missions.get(mid)['stages']['review']==eid


def test_mission_review_snapshot_requires_call_dependencies_in_same_version(funded,durable_api):
    from copy import deepcopy
    from evoforge import missions
    mid=_generated_mission(durable_api)
    phases=[_critic_call_output(p) for p in ('critic_spec','critic_review')]
    eid=_mission_review_output(mid,phases)
    with funded['kernel']._transaction() as conn:
        row=conn.execute('SELECT version,document FROM runtime.api_mission_versions '
                         'WHERE mission_id=%s ORDER BY version DESC LIMIT 1',(mid,)).fetchone()
    document=deepcopy(row['document'])
    document['state']='REVIEWED'
    document['stages']['review']=eid
    document['evidence_ids'].append(eid)
    with pytest.raises(KernelRejected):
        with funded['kernel']._transaction() as conn:
            conn.execute('INSERT INTO runtime.api_mission_versions(tenant_id,project_id,mission_id,version,document) '
                         'VALUES (%s,%s,%s,%s,%s)',
                         (funded['scope'].tenant_id,funded['scope'].project_id,mid,row['version']+1,Jsonb(document)))
    fixed=missions.get(mid)
    assert fixed['state']=='REVIEWED' and all(p in fixed['evidence_ids'] for p in phases)


@pytest.mark.parametrize('bad',['missing','cross_scope','cross_mission','not_provider','duplicate','nonlist'])
def test_mission_review_recovery_refuses_invalid_call_dependencies(funded,durable_api,monkeypatch,bad):
    import main
    from evoforge import missions
    mid=_generated_mission(durable_api)
    before=list(missions.get(mid)['evidence_ids'])
    spec=_critic_call_output('critic_spec')
    if bad=='cross_scope':
        other=uuid4()
        with psycopg.connect(funded['dsn'],autocommit=True) as conn:
            conn.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'other')",
                         (funded['scope'].tenant_id,other))
        with monkeypatch.context() as other_env:
            other_env.setenv('EVO_PROJECT_ID',str(other))
            second=_critic_call_output('critic_review')
    elif bad=='cross_mission':
        other=durable_api.post('/v1/missions',json={'goal':'other','repo_ref':'a'*40}).json()['mission_id']
        second=_critic_call_output('critic_review',mission_id=other)
    elif bad=='not_provider':
        second=_critic_call_output('critic_review',kind='unrelated')
    else:
        second='ev_missing_phase'
    phase_ids={'duplicate':[spec,spec],'nonlist':{'spec':spec}}.get(bad,[spec,second])
    _mission_review_output(mid,phase_ids)
    calls=[]
    monkeypatch.setattr(main.broker_meta,'call_critic',lambda *a,**k:calls.append(True))
    assert durable_api.get('/v1/missions/'+mid).status_code==409
    assert durable_api.post(f'/v1/missions/{mid}/advance',json={'to':'REVIEWED'}).status_code==409
    assert not calls
    with funded['kernel']._transaction() as conn:
        latest=conn.execute('SELECT document FROM runtime.api_mission_versions '
                            'WHERE mission_id=%s ORDER BY version DESC LIMIT 1',(mid,)).fetchone()['document']
    assert latest['state']=='GENERATED' and latest['evidence_ids']==before


@pytest.mark.parametrize('stopped_after',[0,1,2])
def test_mission_review_api_recovers_sdk_calls_after_attachment_failure(durable_api,monkeypatch,stopped_after):
    """Official SDK with in-memory HTTP transport; no paid provider request."""
    import json
    import httpx
    import openai
    import main
    from evoforge import missions,ledger
    mid=_generated_mission(durable_api)
    ledger.reset()
    ledger.configure({'default':50_000})
    monkeypatch.setenv('MODEL_API_KEY','synthetic-recovery-key')
    monkeypatch.setenv('MODEL_API_BASE','https://recovery.fixture.invalid/v1')
    monkeypatch.setenv('MODEL_CRITIC','muse-spark-1.3')
    sealed=[{'kind':kind,'code':'# RECOVERY_SDK_PRIVATE_912\ndef test_contract():\n    assert 2 == 2\n'}
            for kind in ('compositional','negative','boundary')]
    calls,clients,retries=[],[],[]
    def respond(request):
        calls.append(json.loads(request.content))
        content={'sealed_tests':sealed} if len(calls)==1 else {'review':{'result':'PASS','findings':[]}}
        return httpx.Response(200,headers={'x-request-id':f'recovery-request-{len(calls)}'},json={
            'id':f'recovery-completion-{len(calls)}','object':'chat.completion','created':1,'model':'muse-spark-1.3',
            'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(content)}}],
            'usage':{'prompt_tokens':11,'completion_tokens':7,'total_tokens':18}})
    original_client=openai.OpenAI
    def client(**kwargs):
        retries.append(kwargs.get('max_retries'))
        instance=original_client(**kwargs,http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        clients.append(instance)
        return instance
    monkeypatch.setattr(openai,'OpenAI',client)
    attach=missions.attach_evidence
    attached=[]
    def fail_attachment(mid,eid,stage=None):
        if len(attached)==stopped_after:
            raise RuntimeError('injected mission attachment interruption')
        result=attach(mid,eid,stage)
        attached.append(eid)
        return result
    monkeypatch.setattr(missions,'attach_evidence',fail_attachment)
    try:
        broken=durable_api.post(f'/v1/missions/{mid}/advance',json={'to':'REVIEWED'})
        assert broken.status_code==500 and len(calls)==2,broken.text
        monkeypatch.setattr(missions,'attach_evidence',attach)
        restored=durable_api.get('/v1/missions/'+mid)
        assert restored.status_code==200 and restored.json()['state']=='REVIEWED',restored.text
        eid=restored.json()['review_evidence_id']
        phase_ids=main._evidence[eid]['provider_evidence_ids']
        assert len(phase_ids)==2 and all(restored.json()['evidence_ids'].count(p)==1 for p in phase_ids+[eid])
        assert [main._evidence[p]['metadata']['provider_request_id'] for p in phase_ids]==[
            'recovery-request-1','recovery-request-2']
        assert all(c['model']=='muse-spark-1.3' for c in calls) and retries==[0]
        assert 'RECOVERY_SDK_PRIVATE_912' not in durable_api.get('/v1/evidence/'+eid).text
        assert ledger.snapshot()['spent_cents']==2*main.COST_CENTS and ledger.snapshot()['reserved_cents']==0
        assert durable_api.post(f'/v1/missions/{mid}/advance',json={'to':'REVIEWED'}).status_code==409
        assert len(calls)==2
    finally:
        for instance in clients:
            instance.close()
        ledger.reset()
        ledger.configure({'default':50_000})


def test_tenant_prepaid_credit_covers_reservations_hidden_by_project_rls(funded):
    tenant=funded['scope'].tenant_id
    other=uuid4()
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        conn.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'other')",(tenant,other))
        conn.execute('UPDATE core.budgets SET cap_micros=30000000 WHERE tenant_id=%s',(tenant,))
        conn.execute('INSERT INTO core.budgets VALUES (%s,%s,%s,30000000)',(tenant,other,PERIOD))
    first=funded['kernel']
    second=PostgresKernel(funded['dsn'],KernelScope(tenant,other))
    first.reserve_cost(uuid4(),PERIOD,12000000)
    with second._transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM core.cost_reservations').fetchone()['n']==0
    with pytest.raises(BudgetRefused):
        second.reserve_cost(uuid4(),PERIOD,12000000)


def _credit_sibling(funded):
    tenant=funded['scope'].tenant_id
    other=uuid4()
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        conn.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'sibling')",(tenant,other))
        conn.execute('UPDATE core.budgets SET cap_micros=30000000 WHERE tenant_id=%s',(tenant,))
        conn.execute('INSERT INTO core.budgets VALUES (%s,%s,%s,30000000)',(tenant,other,PERIOD))
    return PostgresKernel(funded['dsn'],KernelScope(tenant,other))


def _open_credit_holds(kernel):
    with kernel._transaction() as conn:
        return conn.execute('SELECT runtime.tenant_open_reserved_micros() AS held').fetchone()['held']


def test_tenant_credit_holds_keep_unknown_and_release_only_on_canonical_closure(funded):
    kernel=funded['kernel']
    sibling=_credit_sibling(funded)
    call=uuid4()
    kernel.reserve_cost(call,PERIOD,12000000)
    kernel.mark_sent(call)
    kernel.mark_unknown(call)
    assert _open_credit_holds(sibling)==12000000
    with pytest.raises(BudgetRefused):
        sibling.reserve_cost(uuid4(),PERIOD,10000000)
    with pytest.raises(KernelRejected):
        kernel.release_not_accepted(call)
    receipt=_receipt(funded,call,cost=1000000)
    kernel.settle_reservation(call,receipt,1000000)
    assert _open_credit_holds(sibling)==0
    second=uuid4()
    sibling.reserve_cost(second,PERIOD,19000000)
    assert _open_credit_holds(kernel)==19000000
    sibling.release_not_accepted(second)
    assert _open_credit_holds(kernel)==0
    # Replaying a close does not write another negative hold.
    sibling.release_not_accepted(second)
    kernel.settle_reservation(call,receipt,1000000)
    assert _open_credit_holds(kernel)==0


def test_tenant_credit_hold_release_rolls_back_with_reservation_update(funded):
    kernel=funded['kernel']
    call=uuid4()
    kernel.reserve_cost(call,PERIOD,700)
    with pytest.raises(RuntimeError):
        with kernel._transaction() as conn:
            conn.execute("UPDATE core.cost_reservations SET status='RELEASED' WHERE request_key=%s",(str(call),))
            raise RuntimeError('injected failure after release event')
    assert kernel.reservation(call).status=='RESERVED' and _open_credit_holds(kernel)==700
    kernel.release_not_accepted(call)
    with pytest.raises(KernelRejected):
        with kernel._transaction() as conn:
            conn.execute("UPDATE core.cost_reservations SET status='RESERVED' WHERE request_key=%s",(str(call),))
    assert _open_credit_holds(kernel)==0


def test_parallel_cross_project_credit_holds_stop_at_tenant_balance(funded):
    first=funded['kernel']
    second=_credit_sibling(funded)
    def reserve(i):
        try:
            (first if i%2 else second).reserve_cost(uuid4(),PERIOD,2000000)
            return True
        except BudgetRefused:
            return False
    with ThreadPoolExecutor(max_workers=8) as workers:
        accepted=list(workers.map(reserve,range(24)))
    assert sum(accepted)==10
    assert _open_credit_holds(first)==_open_credit_holds(second)==20000000


def test_tenant_credit_holds_are_isolated_and_private_under_real_core_app(funded):
    tenant,project=uuid4(),uuid4()
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        conn.execute("INSERT INTO core.tenants(tenant_id,name,plan) VALUES (%s,'other','TEAM')",(tenant,))
        conn.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'other')",(tenant,project))
        conn.execute('INSERT INTO core.budgets VALUES (%s,%s,%s,10000000)',(tenant,project,PERIOD))
        conn.execute("INSERT INTO core.usage_ledger(tenant_id,entry_kind,customer_micros,idempotency_key,price_table_version) "
                     "VALUES (%s,'credit_grant',20000000,'other-credit','test')",(tenant,))
    other=PostgresKernel(funded['dsn'],KernelScope(tenant,project))
    other.reserve_cost(uuid4(),PERIOD,8000000)
    assert _open_credit_holds(funded['kernel'])==0
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        conn.execute('SET SESSION AUTHORIZATION core_app')
        conn.execute("SELECT set_config('app.tenant_id',%s,false),set_config('app.project_ids',%s,false)",
                     (str(funded['scope'].tenant_id),str(funded['scope'].project_id)))
        conn.execute('SELECT core.reserve_cost(%s,%s,%s,%s,%s)',
                     (funded['scope'].tenant_id,funded['scope'].project_id,PERIOD,str(uuid4()),600))
        assert conn.execute('SELECT runtime.tenant_open_reserved_micros()').fetchone()[0]==600
        for operation in ('SELECT * FROM runtime.tenant_credit_hold_events',
                          'DELETE FROM runtime.tenant_credit_hold_events',
                          "UPDATE runtime.tenant_credit_hold_events SET amount_micros=1"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(operation)
    assert _open_credit_holds(other)==8000000


def test_tenant_credit_hold_migration_backfills_legacy_rows_and_preserves_force_rls(funded):
    kernel=funded['kernel']
    sibling=_credit_sibling(funded)
    open_call,closed_call=uuid4(),uuid4()
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        original=conn.execute("SELECT pg_get_functiondef('core.reserve_cost(uuid,uuid,date,text,bigint)'::regprocedure)").fetchone()[0]
        conn.execute('ALTER TABLE core.cost_reservations DISABLE TRIGGER tenant_credit_hold')
        try:
            # Seed historical canonical rows, as created before adapter/007.
            for scoped,call,amount in ((kernel,open_call,12000000),(sibling,uuid4(),12000000),(sibling,closed_call,100)):
                with scoped._transaction() as legacy:
                    legacy.execute('SELECT core.reserve_cost(%s,%s,%s,%s,%s)',
                                   (scoped.scope.tenant_id,scoped.scope.project_id,PERIOD,str(call),amount))
            with sibling._transaction() as legacy:
                legacy.execute("UPDATE core.cost_reservations SET status='RELEASED' WHERE request_key=%s",(str(closed_call),))
        finally:
            conn.execute('ALTER TABLE core.cost_reservations ENABLE TRIGGER tenant_credit_hold')
        migration=(ROOT/'services/api/migrations/007_tenant_credit_holds.sql').read_text(encoding='utf-8')
        conn.execute(migration)
        conn.execute(migration)
        current=conn.execute("SELECT pg_get_functiondef('core.reserve_cost(uuid,uuid,date,text,bigint)'::regprocedure)").fetchone()[0]
        assert current==original
        flags=conn.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                           "WHERE oid IN ('core.cost_reservations'::regclass,'runtime.tenant_credit_hold_events'::regclass)").fetchall()
        assert flags==[(True,True),(True,True)]
    assert _open_credit_holds(kernel)==_open_credit_holds(sibling)==24000000
    with pytest.raises(BudgetRefused):
        sibling.reserve_cost(uuid4(),PERIOD,1)
    with kernel._transaction() as conn:
        assert conn.execute('SELECT status FROM core.cost_reservations WHERE request_key=%s',(str(open_call),)).fetchone()['status']=='RESERVED'


def test_tenant_credit_guard_disabled_refuses_reservation_without_side_effects(funded,http_kernel):
    call=uuid4()
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        conn.execute('ALTER TABLE core.cost_reservations DISABLE TRIGGER tenant_credit_hold')
        try:
            response=http_kernel.post('/v1/kernel/reservations',json={
                'call_id':str(call),'period_start':PERIOD.isoformat(),'amount_micros':100})
            assert response.status_code==503,response.text
            with funded['kernel']._transaction() as check:
                assert check.execute('SELECT count(*) AS n FROM core.cost_reservations').fetchone()['n']==0
                assert check.execute('SELECT count(*) AS n FROM core.side_effect_intents').fetchone()['n']==0
        finally:
            conn.execute('ALTER TABLE core.cost_reservations ENABLE TRIGGER tenant_credit_hold')
    assert funded['kernel'].reserve_cost(call,PERIOD,100).status=='RESERVED'


def test_tenant_credit_guard_rejects_connections_that_skip_origin_triggers(funded):
    from evoforge.postgres_kernel import KernelUnavailable
    unsafe=PostgresKernel(make_conninfo(funded['dsn'],options='-c session_replication_role=replica'),funded['scope'])
    with pytest.raises(KernelUnavailable):
        unsafe.reserve_cost(uuid4(),PERIOD,100)
    with funded['kernel']._transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM core.cost_reservations').fetchone()['n']==0
        assert conn.execute('SELECT count(*) AS n FROM core.side_effect_intents').fetchone()['n']==0


@pytest.fixture
def builder_proposal(funded,durable_api,http_kernel,monkeypatch,tmp_path):
    """Real Git/PostgreSQL; synthetic Builder, receipt and remote checkout transport."""
    import main
    import tempfile
    from evoforge import repo_source
    repo=tmp_path/'proposal-source'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
    git('init','-q')
    git('config','user.name','Fixture')
    git('config','user.email','fixture@example.invalid')
    (repo/'value.py').write_text('result = 2\n',encoding='utf-8')
    git('add','value.py')
    git('commit','-qm','base')
    base=git('rev-parse','HEAD')
    diff='--- a/value.py\n+++ b/value.py\n@@ -1 +1 @@\n-result = 2\n+result = 3\n'
    visible='from value import result\ndef f_ref():\n    return 3\ndef test_value():\n    assert result == f_ref()\n'
    (repo/'value.py').write_text('result = 3\n',encoding='utf-8')
    git('commit','-qam','patch')
    patch_head=git('rev-parse','HEAD')
    target=repo/'tests/evoforge_gen/test_gen_1.py'
    target.parent.mkdir(parents=True)
    target.write_text(visible,encoding='utf-8')
    git('add','tests')
    git('commit','-qm','visible tests')
    head=git('rev-parse','HEAD')
    context=_builder_packet(funded,base_sha=base)
    call=uuid4()
    _prepare(funded,context['packet'],call)
    funded['kernel'].mark_sent(call)
    receipt=receipt_document(tenant=funded['scope'].tenant_id,project=funded['scope'].project_id,
                             packet=context['packet'],call=call)
    funded['kernel'].record_receipt(receipt)
    funded['kernel'].settle_from_receipt(receipt['receipt_id'])
    candidate={'diff':diff,'tests':[{'code':visible}],'stub':False,'model':'muse-spark-1.3',
               'provider_calls':[{'provider':'meta','model':'muse-spark-1.3','phase':'builder',
                                  'provider_request_id':receipt['provider_request_id']}]}
    monkeypatch.setattr(main.broker_meta,'call_builder',lambda *a,**k:candidate)
    generated=durable_api.post('/v1/commands/generate',json={'goal':'result is 3','repo_sha':base,'idempotency_key':uuid4().hex})
    assert generated.status_code==200,generated.text
    eid=generated.json()['evidence']['id']
    clones=[]
    original=repo_source.resolve_repo_dir
    def resolve(source,ref):
        if source!='':
            return original(source,ref)
        clone=Path(tempfile.mkdtemp(prefix='evoforge-remote-'))
        clones.append(clone)
        subprocess.check_call(['git','clone','-q','--no-hardlinks',str(repo),str(clone)])
        subprocess.check_call(['git','-C',str(clone),'checkout','--detach','-q',ref])
        return str(clone)
    monkeypatch.setattr(repo_source,'resolve_repo_dir',resolve)
    monkeypatch.setenv('EVO_ALLOW_LOCAL_REPOS','1')
    monkeypatch.setenv('EVO_REPO_ROOTS',str(tmp_path))
    monkeypatch.setenv('EVO_RUNNER_URL','')
    monkeypatch.setenv('EVO_RUNNER_IMAGE_DIGEST','sha256:'+'7'*64)
    return {'call':call,'context':context,'receipt':receipt,'repo':repo,'git':git,'base':base,'head':head,
            'patch_head':patch_head,'candidate':candidate,'evidence':eid,'clones':clones,'api':durable_api,'http':http_kernel}


def _propose(ctx,**change):
    return ctx['http'].post('/v1/kernel/candidates',json={
        'call_id':str(ctx['call']),'evidence_id':ctx['evidence'],'head_sha':ctx['head'],**change})


def test_registered_builder_proposal_survives_restart_and_links_real_runner_only_to_verified_head(funded,builder_proposal,monkeypatch):
    import main
    from evoforge.postgres_candidates import register
    ctx=builder_proposal
    with ThreadPoolExecutor(max_workers=4) as workers:
        rows=list(workers.map(lambda _:register(funded['kernel'],ctx['call'],ctx['evidence'],ctx['head']),range(8)))
    ids={r['candidate_id'] for r in rows}
    assert len(ids)==1 and all(r['status']=='PROPOSED' for r in rows)
    candidate=next(iter(ids))
    result=_propose(ctx)
    assert result.status_code==200 and result.json()['candidate_id']==str(candidate),result.text
    assert all(not clone.exists() for clone in ctx['clones'])
    with funded['kernel']._transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM core.candidates').fetchone()['n']==1
        assert conn.execute('SELECT count(*) AS n FROM core.gate_results').fetchone()['n']==0
    script="""import os
import main
from fastapi.testclient import TestClient
with TestClient(main.app) as c:
    r=c.get('/v1/kernel/candidates/'+os.environ['CHECK_REGISTERED_CANDIDATE'],
            headers={'Authorization':'Bearer '+os.environ['EVO_KERNEL_TOKEN']})
    assert r.status_code==200 and r.json()['head_sha']==os.environ['CHECK_REGISTERED_HEAD']
    print(r.json()['candidate_id'])
"""
    child=subprocess.run([sys.executable,'-c',script],cwd=ROOT/'services/api',capture_output=True,text=True,timeout=20,
                         env={**os.environ,'CHECK_REGISTERED_CANDIDATE':str(candidate),'CHECK_REGISTERED_HEAD':ctx['head']},
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert child.returncode==0 and child.stdout.strip()==str(candidate)
    sealed=[{'kind':kind,'code':f'# REGISTERED_PRIVATE_631\nfrom value import result\ndef test_{kind}():\n    assert result == 3\n'}
            for kind in ('compositional','negative','boundary')]
    monkeypatch.setattr(main.broker_meta,'call_critic',lambda *a,**k:{
        'sealed_tests':sealed,'stub':False,'model':'muse-spark-1.3','review':{'result':'PASS'}})
    review=ctx['api'].post('/v1/candidates/review',json={'goal_contract':'result is 3'})
    run=ctx['api'].post('/v1/runs',json={'source_repo':str(ctx['repo']),'base_sha':ctx['head'],'diff':'',
        'tests':ctx['candidate']['tests'],'review_evidence_id':review.json()['evidence_id']})
    assert run.status_code==200,run.text
    body={'candidate_id':str(candidate),'call_id':str(ctx['call']),'evidence_id':run.json()['evidence_id']}
    linked=ctx['http'].post('/v1/kernel/candidate-runs',json=body)
    assert linked.status_code==200 and linked.json()['result']=='PASS',linked.text
    assert 'REGISTERED_PRIVATE_631' not in linked.text
    assert ctx['http'].post('/v1/kernel/merge-authorizations',json={
        'candidate_id':str(candidate),'head_sha':ctx['head'],'policy_hash':'1'*64}).status_code==409
    with funded['kernel']._transaction() as conn:
        conn.execute('UPDATE core.candidates SET head_sha=%s WHERE candidate_id=%s',('f'*40,candidate))
    assert _propose(ctx).status_code==409
    assert ctx['http'].post('/v1/kernel/candidate-runs',json=body).status_code==409
    with monkeypatch.context() as scope:
        scope.setenv('EVO_PROJECT_ID',str(uuid4()))
        assert ctx['http'].get('/v1/kernel/candidates/'+str(candidate)).status_code==404


def test_registered_candidate_rejects_unbound_builder_metadata_without_git_or_partial_rows(funded,builder_proposal):
    import main
    from copy import deepcopy
    ctx=builder_proposal
    for change in ('stub','model','request','phase','calls','tests'):
        record=deepcopy(main._evidence[ctx['evidence']])
        record.pop('id')
        candidate=record['candidate']
        if change=='stub': candidate['stub']=True
        elif change=='model': candidate['model']='different-model'
        elif change=='request': candidate['provider_calls'][0]['provider_request_id']='another-call'
        elif change=='phase': candidate['provider_calls'][0]['phase']='critic_spec'
        elif change=='calls': candidate['provider_calls']=[]
        else: candidate['tests']=[]
        eid=main._store_evidence(record)
        main._link_stages(eid,('Task','Candidate','Gate'))
        assert _propose(ctx,evidence_id=eid).status_code==409,change
    pending=uuid4()
    _prepare(funded,ctx['context']['packet'],pending)
    assert _propose(ctx,call_id=str(pending)).status_code==409
    with funded['kernel']._transaction() as conn:
        conn.execute('UPDATE core.cost_reservations SET actual_micros=actual_micros+1 WHERE request_key=%s',(str(ctx['call']),))
    assert _propose(ctx).status_code==409
    assert ctx['clones']==[]
    with funded['kernel']._transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM core.candidates').fetchone()['n']==0
    assert funded['kernel'].reservation(ctx['call']).status=='COMMITTED'


def test_registered_candidate_rejects_git_content_tests_and_unrelated_changes(funded,builder_proposal):
    import main
    from copy import deepcopy
    ctx=builder_proposal
    assert _propose(ctx,head_sha=ctx['patch_head']).status_code==409
    (ctx['repo']/'unrelated.txt').write_text('extra change\n',encoding='utf-8')
    ctx['git']('add','unrelated.txt')
    ctx['git']('commit','-qm','unrelated')
    assert _propose(ctx,head_sha=ctx['git']('rev-parse','HEAD')).status_code==409
    record=deepcopy(main._evidence[ctx['evidence']])
    record.pop('id')
    record['candidate']['diff']=record['candidate']['diff'].replace('+result = 3','+result = 4')
    eid=main._store_evidence(record)
    main._link_stages(eid,('Task','Candidate','Gate'))
    assert _propose(ctx,evidence_id=eid).status_code==409
    assert ctx['clones'] and all(not clone.exists() for clone in ctx['clones'])
    with funded['kernel']._transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM core.candidates').fetchone()['n']==0


def test_registered_candidate_rechecks_fencing_after_git_and_rolls_back_registration(funded,builder_proposal,monkeypatch):
    from evoforge import postgres_candidates
    ctx=builder_proposal
    verify=postgres_candidates.verify_head
    def revoked(*args):
        tree=verify(*args)
        with psycopg.connect(funded['dsn'],autocommit=True) as conn:
            conn.execute('UPDATE core.tasks SET lease_epoch=lease_epoch+1 WHERE task_id=%s',(ctx['context']['task'],))
        return tree
    monkeypatch.setattr(postgres_candidates,'verify_head',revoked)
    assert _propose(ctx).status_code==409
    with funded['kernel']._transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM core.candidates').fetchone()['n']==0
        assert conn.execute('SELECT count(*) AS n FROM runtime.builder_candidate_evidence').fetchone()['n']==0
    assert all(not clone.exists() for clone in ctx['clones'])


def test_registered_candidate_binding_failure_rolls_back_core_candidate(funded,builder_proposal):
    ctx=builder_proposal
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        conn.execute("CREATE FUNCTION runtime.test_reject_candidate_binding() RETURNS trigger LANGUAGE plpgsql AS $$ "
                     "BEGIN RAISE EXCEPTION 'injected binding failure' USING ERRCODE='check_violation'; END $$")
        conn.execute('CREATE TRIGGER test_reject_candidate_binding BEFORE INSERT ON runtime.builder_candidate_evidence '
                     'FOR EACH ROW EXECUTE FUNCTION runtime.test_reject_candidate_binding()')
        try:
            response=_propose(ctx)
            assert response.status_code==409,response.text
            with funded['kernel']._transaction() as check:
                assert check.execute('SELECT count(*) AS n FROM core.candidates').fetchone()['n']==0
                assert check.execute('SELECT count(*) AS n FROM runtime.builder_candidate_evidence').fetchone()['n']==0
        finally:
            conn.execute('DROP TRIGGER test_reject_candidate_binding ON runtime.builder_candidate_evidence')
            conn.execute('DROP FUNCTION runtime.test_reject_candidate_binding()')
    assert _propose(ctx).status_code==200
    assert funded['kernel'].reservation(ctx['call']).status=='COMMITTED'
    assert all(not clone.exists() for clone in ctx['clones'])


def test_project_cap_rechecks_settlement_that_commits_after_initial_reserve_check(funded):
    kernel=funded['kernel']
    prior,incoming=uuid4(),uuid4()
    pause='evo.test.cap:'+uuid4().hex
    with psycopg.connect(funded['dsn'],autocommit=True) as control:
        control.execute('UPDATE core.budgets SET cap_micros=1000 WHERE tenant_id=%s AND project_id=%s',
                        (funded['scope'].tenant_id,funded['scope'].project_id))
        kernel.reserve_cost(prior,PERIOD,100)
        kernel.mark_sent(prior)
        receipt=_receipt(funded,prior,cost=900)
        control.execute("CREATE FUNCTION runtime.test_pause_cap_insert() RETURNS trigger LANGUAGE plpgsql AS $$ "
                        f"BEGIN IF NEW.request_key='{incoming}' THEN "
                        f"PERFORM pg_advisory_xact_lock(hashtextextended('{pause}',0)); END IF; RETURN NEW; END $$")
        control.execute('CREATE TRIGGER test_pause_cap_insert BEFORE INSERT ON core.cost_reservations '
                        'FOR EACH ROW EXECUTE FUNCTION runtime.test_pause_cap_insert()')
        control.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',(pause,))
        try:
            with ThreadPoolExecutor(max_workers=1) as workers:
                queued=workers.submit(kernel.reserve_cost,incoming,PERIOD,900)
                try:
                    deadline=time.monotonic()+8
                    while time.monotonic()<deadline:
                        waiting=control.execute("SELECT EXISTS(SELECT 1 FROM pg_locks l JOIN pg_stat_activity a USING(pid) "
                                                "WHERE l.locktype='advisory' AND NOT l.granted AND a.datname=current_database())").fetchone()[0]
                        if waiting:
                            break
                        time.sleep(0.02)
                    assert waiting,'new reservation did not reach the post-cap-check pause'
                    # The request passed the original 100 + 900 <= 1000 check.
                    # Now settle the old reservation at 900 before INSERT finishes.
                    assert kernel.settle_reservation(prior,receipt,900).actual_micros==900
                finally:
                    control.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(pause,))
                with pytest.raises(BudgetRefused):
                    queued.result(timeout=10)
        finally:
            control.execute('DROP TRIGGER test_pause_cap_insert ON core.cost_reservations')
            control.execute('DROP FUNCTION runtime.test_pause_cap_insert()')
    assert kernel.reservation(prior).status=='COMMITTED'
    with pytest.raises(KernelNotFound):
        kernel.reservation(incoming)
    assert _open_credit_holds(kernel)==0
    assert kernel.reserve_cost(uuid4(),PERIOD,100).reserved_micros==100
    assert _open_credit_holds(kernel)==100


def _merge_ready(funded,risk='LOW'):
    """Synthetic gate/review/approval evidence, only for deterministic DB authorization checks."""
    scope=funded['scope']
    author,reviewer,run,task,candidate=(uuid4() for _ in range(5))
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        for agent in (author,reviewer):
            conn.execute("INSERT INTO core.agents(tenant_id,agent_id,kind) VALUES (%s,%s,'provider_api')",(scope.tenant_id,agent))
        conn.execute("INSERT INTO core.runs(tenant_id,project_id,run_id,objective_version,topology,harness_version,policy_hash) "
                     "VALUES (%s,%s,%s,1,'SINGLE','test',%s)",(scope.tenant_id,scope.project_id,run,'1'*64))
        conn.execute('INSERT INTO core.tasks(tenant_id,project_id,task_id,run_id,risk_level) VALUES (%s,%s,%s,%s,%s)',
                     (scope.tenant_id,scope.project_id,task,run,risk))
        conn.execute('INSERT INTO core.candidates(tenant_id,project_id,candidate_id,task_id,author_agent_id,base_sha,head_sha) '
                     'VALUES (%s,%s,%s,%s,%s,%s,%s)',(scope.tenant_id,scope.project_id,candidate,task,author,'a'*40,'b'*40))
        for gate in ('G0_SCOPE','G1_IMPACTED','G2_REQUIRED','GH_INTEGRITY','GR_REVIEW','G4_MERGE_HEAD'):
            conn.execute('INSERT INTO core.gate_results(tenant_id,project_id,candidate_id,gate,result,head_sha,policy_hash,'
                         "runner_image_digest,evidence_sha256) VALUES (%s,%s,%s,%s,'PASS',%s,%s,'sha256:fixture',%s)",
                         (scope.tenant_id,scope.project_id,candidate,gate,'b'*40,'1'*64,'e'*64))
        conn.execute('INSERT INTO core.reviews(tenant_id,project_id,candidate_id,reviewer_agent_id,verdict,head_sha,'
                     'context_independent,spec_tests_sealed_at,diff_first_read_at) '
                     "VALUES (%s,%s,%s,%s,'approve',%s,true,now()-interval '2 seconds',now()-interval '1 second')",
                     (scope.tenant_id,scope.project_id,candidate,reviewer,'b'*40))
        if risk in ('HIGH','CRITICAL'):
            conn.execute('INSERT INTO core.approvals(tenant_id,project_id,subject_kind,subject_id,resource_sha,approver_user_id,reauthenticated) '
                         "VALUES (%s,%s,'merge',%s,%s,%s,true)",(scope.tenant_id,scope.project_id,candidate,'b'*40,uuid4()))
    return {'candidate':candidate,'reviewer':reviewer,'run':run,'risk':risk}


def test_merge_authorization_rejects_old_policy_after_run_policy_changes(funded,http_kernel):
    ctx=_merge_ready(funded)
    body={'candidate_id':str(ctx['candidate']),'head_sha':'b'*40,'policy_hash':'1'*64}
    assert http_kernel.post('/v1/kernel/merge-authorizations',json=body).status_code==200
    with psycopg.connect(funded['dsn'],autocommit=True) as conn:
        conn.execute('UPDATE core.runs SET policy_hash=%s WHERE run_id=%s',('2'*64,ctx['run']))
    assert http_kernel.post('/v1/kernel/merge-authorizations',json=body).status_code==409
    # The current policy also needs its own gates; the old PASS rows cannot be reused.
    assert http_kernel.post('/v1/kernel/merge-authorizations',json={**body,'policy_hash':'2'*64}).status_code==409


def test_merge_authorization_rejects_qualification_expired_during_transaction(funded,monkeypatch):
    from contextlib import contextmanager
    ctx=_merge_ready(funded,'HIGH')
    kernel=funded['kernel']
    original=kernel._transaction
    @contextmanager
    def delayed():
        with original() as conn:
            started=conn.execute('SELECT now() AS ts').fetchone()['ts']
            with psycopg.connect(funded['dsn'],autocommit=True) as issuer:
                issuer.execute('INSERT INTO core.reviewer_qualifications(tenant_id,agent_id,risk_level,harness_version,'
                               'qualified_at,expires_at,evidence_sha256) '
                               "VALUES (%s,%s,'HIGH','test',%s,clock_timestamp()+interval '200 milliseconds',%s)",
                               (funded['scope'].tenant_id,ctx['reviewer'],started,'e'*64))
            conn.execute('SELECT pg_sleep(0.4)')
            yield conn
    monkeypatch.setattr(kernel,'_transaction',delayed)
    with pytest.raises(KernelRejected):
        kernel.authorize_merge(ctx['candidate'],'b'*40,'1'*64)
    monkeypatch.setattr(kernel,'_transaction',original)
    with psycopg.connect(funded['dsn'],autocommit=True) as issuer:
        issuer.execute('INSERT INTO core.reviewer_qualifications(tenant_id,agent_id,risk_level,harness_version,'
                       'qualified_at,expires_at,evidence_sha256) '
                       "VALUES (%s,%s,'HIGH','test',clock_timestamp(),clock_timestamp()+interval '1 hour',%s)",
                       (funded['scope'].tenant_id,ctx['reviewer'],'f'*64))
    kernel.authorize_merge(ctx['candidate'],'b'*40,'1'*64)


@pytest.mark.parametrize('kind', ['provider_billed', 'estimated', 'zero'])
def test_receipt_aware_release_keeps_recorded_usage_reserved_for_reconciliation(funded, kind):
    document, kernel = _document(funded), funded['kernel']
    if kind == 'estimated':
        document['source'] = 'estimated'
    elif kind == 'zero':
        document['cost_micros'] = document['customer_price_micros'] = 0
    kernel.record_receipt(document)
    restarted = PostgresKernel(funded['dsn'], funded['scope'])
    with pytest.raises(KernelRejected):
        restarted.release_not_accepted(document['call_id'])
    state = restarted.reservation(document['call_id'])
    assert (state.status, state.outcome, state.actual_micros) == ('RESERVED', 'SENT', None)
    assert restarted.receipt_document(document['receipt_id'])['ledger_entry_id'] is None
    with restarted._transaction() as conn:
        assert conn.execute('SELECT runtime.tenant_open_reserved_micros() AS held').fetchone()['held'] == 100
    if kind == 'zero':
        # A zero quote still cannot bypass the unresolved canonical zero-charge policy.
        with pytest.raises(ValueError):
            restarted.settle_from_receipt(document['receipt_id'])
        assert restarted.reservation(document['call_id']).status == 'RESERVED'
    else:
        assert restarted.settle_from_receipt(document['receipt_id']).actual_micros == 110
        assert restarted.settle_from_receipt(document['receipt_id']).status == 'COMMITTED'


@pytest.mark.parametrize('referenced', [True, False])
def test_receipt_aware_release_also_preserves_legacy_usage_without_document(funded, referenced):
    kernel, call = funded['kernel'], uuid4()
    kernel.reserve_cost(call, PERIOD, 100)
    kernel.mark_sent(call)
    rid = _receipt(funded, call, referenced=referenced)
    with pytest.raises(KernelRejected):
        kernel.release_not_accepted(call)
    assert kernel.reservation(call).status == 'RESERVED'
    if referenced:
        assert kernel.settle_reservation(call, rid, 110).status == 'COMMITTED'
    else:
        with pytest.raises(KernelRejected):
            kernel.settle_reservation(call, rid, 110)
        assert kernel.reservation(call).status == 'RESERVED'


def test_receipt_aware_release_http_refuses_refund_then_settles_stored_quote(funded, http_kernel):
    document = _document(funded)
    call, rid = document['call_id'], document['receipt_id']
    assert http_kernel.post('/v1/kernel/receipts', json=document).status_code == 200
    assert http_kernel.post(f'/v1/kernel/reservations/{call}/release-not-accepted').status_code == 409
    state = http_kernel.get(f'/v1/kernel/reservations/{call}').json()
    assert (state['status'], state['outcome']) == ('RESERVED', 'SENT')
    assert http_kernel.post(f'/v1/kernel/receipts/{rid}/settle', json={}).json()['status'] == 'COMMITTED'
    assert http_kernel.post(f'/v1/kernel/receipts/{rid}/settle', json={}).json()['actual_micros'] == 110


def test_receipt_aware_release_rechecks_usage_after_waiting_for_recording_transaction(funded, monkeypatch):
    from contextlib import contextmanager
    from threading import Event
    document = _document(funded)
    recorder = PostgresKernel(funded['dsn'], funded['scope'])
    releaser = PostgresKernel(funded['dsn'], funded['scope'])
    original_transaction, original_read = recorder._transaction, releaser._read
    stored, release_started, finish_record = Event(), Event(), Event()
    release_backend = []

    @contextmanager
    def pause_before_commit():
        with original_transaction() as conn:
            yield conn
            stored.set()
            assert finish_record.wait(10), 'recording transaction was not released'

    def signal_read(conn, call_id, *, lock=False):
        if lock:
            release_backend.append(conn.info.backend_pid)
            release_started.set()
        return original_read(conn, call_id, lock=lock)

    monkeypatch.setattr(recorder, '_transaction', pause_before_commit)
    monkeypatch.setattr(releaser, '_read', signal_read)
    with ThreadPoolExecutor(max_workers=2) as workers:
        recording = workers.submit(recorder.record_receipt, document)
        try:
            assert stored.wait(10), 'receipt was not inserted before release'
            releasing = workers.submit(releaser.release_not_accepted, document['call_id'])
            assert release_started.wait(10)
            with psycopg.connect(funded['dsn'], autocommit=True) as observer:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    wait = observer.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s',
                                            (release_backend[0],)).fetchone()
                    if wait and wait[0] == 'Lock':
                        break
                    time.sleep(0.01)
                else:
                    pytest.fail('release did not wait for the reservation row lock')
        finally:
            finish_record.set()
        assert recording.result(timeout=10)['ledger_entry_id'] is None
        with pytest.raises(KernelRejected):
            releasing.result(timeout=10)
    assert funded['kernel'].reservation(document['call_id']).status == 'RESERVED'
    assert funded['kernel'].settle_from_receipt(document['receipt_id']).status == 'COMMITTED'


def test_receipt_aware_release_ignores_other_calls_and_other_project_receipts(funded):
    document, kernel = _document(funded), funded['kernel']
    kernel.record_receipt(document)
    call = uuid4()
    kernel.reserve_cost(call, PERIOD, 100)
    kernel.mark_sent(call)
    other_project = uuid4()
    scope = funded['scope']
    with psycopg.connect(funded['dsn'], autocommit=True) as conn:
        conn.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'other')",
                     (scope.tenant_id, other_project))
    _receipt({'dsn': funded['dsn'], 'scope': KernelScope(scope.tenant_id, other_project)}, call)
    state = kernel.release_not_accepted(call)
    assert (state.status, state.outcome) == ('RELEASED', 'FAILED')
    assert kernel.release_not_accepted(call) == state
    assert kernel.reservation(document['call_id']).status == 'RESERVED'


@contextmanager
def _usage_guard_session(funded, role):
    with psycopg.connect(funded['dsn'], autocommit=True) as conn:
        conn.execute(sql.SQL('SET SESSION AUTHORIZATION {}').format(sql.Identifier(role)))
        with conn.transaction():
            conn.execute("SELECT set_config('app.tenant_id',%s,true),set_config('app.project_ids',%s,true)",
                         (str(funded['scope'].tenant_id), str(funded['scope'].project_id)))
            yield conn


def _insert_direct_usage(conn, document):
    conn.execute('INSERT INTO ctx.provider_usage_receipts '
                 '(tenant_id,project_id,receipt_id,packet_id,call_id,call_purpose,provider,model,'
                 'provider_request_id,source,billing_owner,uncached_input,cache_write,cache_read,'
                 'output_tokens,raw_usage_fields,cost_micros,price_table_version) '
                 "VALUES (%s,%s,%s,%s,%s,'task_turn','meta','muse-spark-1.3',%s,'provider_billed','platform',"
                 '11,0,3,7,%s,80,%s)',
                 (document['tenant_id'], document['project_id'], document['receipt_id'], document['packet_id'],
                  document['call_id'], document['provider_request_id'], Jsonb(document['raw_usage_fields']),
                  document['price_table_version']))


def _release_direct_usage(conn, document):
    conn.execute("UPDATE core.cost_reservations SET status='RELEASED' WHERE request_key=%s",
                 (document['call_id'],))


def test_database_usage_guard_refuses_direct_release_and_rolls_back_intent_change(funded):
    document, kernel = _document(funded), funded['kernel']
    kernel.record_receipt(document)
    with pytest.raises(psycopg.errors.CheckViolation):
        with _usage_guard_session(funded, 'core_app') as conn:
            conn.execute("UPDATE core.side_effect_intents SET status='FAILED' WHERE idempotency_key=%s",
                         (kernel._intent_key(UUID(document['call_id'])),))
            _release_direct_usage(conn, document)
    state = kernel.reservation(document['call_id'])
    assert (state.status, state.outcome) == ('RESERVED', 'SENT')
    assert _open_credit_holds(kernel) == 100
    assert kernel.settle_from_receipt(document['receipt_id']).status == 'COMMITTED'


def test_database_usage_guard_refuses_direct_receipt_after_reservation_release(funded):
    document, kernel = _document(funded), funded['kernel']
    kernel.release_not_accepted(document['call_id'])
    with pytest.raises(psycopg.errors.CheckViolation):
        with _usage_guard_session(funded, 'ctx_gateway') as conn:
            _insert_direct_usage(conn, document)
    with _usage_guard_session(funded, 'ctx_gateway') as conn:
        assert conn.execute('SELECT count(*) FROM ctx.provider_usage_receipts WHERE call_id=%s',
                            (document['call_id'],)).fetchone()[0] == 0
    assert kernel.reservation(document['call_id']).status == 'RELEASED'
    assert _open_credit_holds(kernel) == 0


@pytest.mark.parametrize('first', ['receipt', 'release'])
def test_database_usage_guard_serializes_independent_writer_and_release(funded, first):
    from threading import Event
    document, kernel = _document(funded), funded['kernel']
    ready, attempted, finish = Event(), Event(), Event()
    waiting_pid = []
    actions = {'receipt': ('ctx_gateway', _insert_direct_usage), 'release': ('core_app', _release_direct_usage)}

    def initial():
        role, action = actions[first]
        with _usage_guard_session(funded, role) as conn:
            action(conn, document)
            ready.set()
            assert finish.wait(10)

    def concurrent():
        role, action = actions['release' if first == 'receipt' else 'receipt']
        with _usage_guard_session(funded, role) as conn:
            waiting_pid.append(conn.info.backend_pid)
            attempted.set()
            action(conn, document)

    with ThreadPoolExecutor(max_workers=2) as workers:
        initial_result = workers.submit(initial)
        try:
            assert ready.wait(10)
            concurrent_result = workers.submit(concurrent)
            assert attempted.wait(10)
            with psycopg.connect(funded['dsn'], autocommit=True) as observer:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    row = observer.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s',
                                           (waiting_pid[0],)).fetchone()
                    if row and row[0] == 'Lock':
                        break
                    assert not concurrent_result.done(), 'concurrent operation bypassed reservation lock'
                    time.sleep(0.01)
                else:
                    pytest.fail('concurrent writer did not wait for reservation lock')
        finally:
            finish.set()
        initial_result.result(timeout=10)
        with pytest.raises(psycopg.errors.CheckViolation):
            concurrent_result.result(timeout=10)
    assert kernel.reservation(document['call_id']).status == ('RESERVED' if first == 'receipt' else 'RELEASED')
    assert _open_credit_holds(kernel) == (100 if first == 'receipt' else 0)


@pytest.mark.parametrize('relation,trigger', [
    ('core.cost_reservations', 'usage_release_guard'),
    ('ctx.provider_usage_receipts', 'usage_reservation_lock'),
])
@pytest.mark.parametrize('mode', ['disabled', 'replica', 'missing'])
def test_database_usage_guard_unavailable_blocks_reserve_send_and_release(funded, http_kernel, relation, trigger, mode):
    kernel, call = funded['kernel'], uuid4()
    kernel.reserve_cost(call, PERIOD, 100)
    with psycopg.connect(funded['dsn'], autocommit=True) as admin:
        installed = admin.execute('SELECT 1 FROM pg_trigger WHERE tgrelid=%s::regclass AND tgname=%s',
                                  (relation, trigger)).fetchone()
        if installed:
            target = sql.SQL(relation)
            if mode == 'missing':
                admin.execute(sql.SQL('DROP TRIGGER {} ON {}').format(sql.Identifier(trigger), target))
            else:
                alteration = sql.SQL('DISABLE TRIGGER') if mode == 'disabled' else sql.SQL('ENABLE REPLICA TRIGGER')
                admin.execute(sql.SQL('ALTER TABLE {} {} {}').format(target, alteration, sql.Identifier(trigger)))
        try:
            fresh = uuid4()
            assert http_kernel.post('/v1/kernel/reservations', json={
                'call_id': str(fresh), 'period_start': PERIOD.isoformat(), 'amount_micros': 100}).status_code == 503
            assert http_kernel.post(f'/v1/kernel/reservations/{call}/sent').status_code == 503
            assert http_kernel.post(f'/v1/kernel/reservations/{call}/release-not-accepted').status_code == 503
            with pytest.raises(KernelNotFound):
                kernel.reservation(fresh)
            assert kernel.reservation(call).outcome == 'RESERVED'
            assert _open_credit_holds(kernel) == 100
        finally:
            if installed:
                admin.execute((ROOT/'services/api/migrations/009_usage_release_guards.sql').read_text(encoding='utf-8'))
    assert kernel.mark_sent(call).outcome == 'SENT'
    assert kernel.release_not_accepted(call).status == 'RELEASED'


def test_database_usage_guard_migration_preserves_contracts_rls_and_restricts_helpers(funded):
    with psycopg.connect(funded['dsn'], autocommit=True) as admin:
        def contract_state():
            functions = admin.execute("SELECT oid::regprocedure::text,pg_get_functiondef(oid) FROM pg_proc "
                                      "WHERE pronamespace='core'::regnamespace ORDER BY oid").fetchall()
            policies = admin.execute("SELECT schemaname,tablename,policyname,roles,qual,with_check FROM pg_policies "
                                     "WHERE schemaname IN ('ctx','core') ORDER BY schemaname,tablename,policyname").fetchall()
            return functions, policies
        before = contract_state()
        ddl = (ROOT/'services/api/migrations/009_usage_release_guards.sql').read_text(encoding='utf-8')
        admin.execute(ddl)
        admin.execute(ddl)
        assert contract_state() == before
        assert admin.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid IN "
                             "('core.cost_reservations'::regclass,'ctx.provider_usage_receipts'::regclass)").fetchall() == [(True, True)]*2
        for role in ('core_app', 'ctx_gateway'):
            for function in ('runtime.lock_usage_reservation()', 'runtime.reject_usage_release()'):
                assert not admin.execute('SELECT has_function_privilege(%s,%s,\'EXECUTE\')', (role, function)).fetchone()[0]
        assert not admin.execute("SELECT has_schema_privilege('core_owner','runtime','CREATE')").fetchone()[0]
    with _usage_guard_session(funded, 'ctx_gateway') as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT * FROM core.cost_reservations')


def _tagged_candidate_run(ctx, monkeypatch):
    """Use the actual local Runner and server evidence; provider outputs are synthetic."""
    import main
    sealed = [{'kind': kind, 'code': f'from value import result\ndef test_{kind}():\n    assert result == 3\n'}
              for kind in ('compositional', 'negative', 'boundary')]
    monkeypatch.setattr(main.broker_meta, 'call_critic', lambda *a, **k: {
        'sealed_tests': sealed, 'stub': False, 'model': 'muse-spark-1.3', 'review': {'result': 'PASS'}})
    review = ctx['api'].post('/v1/candidates/review', json={'goal_contract': 'result is 3'})
    assert review.status_code == 200, review.text
    result = ctx['api'].post('/v1/runs', json={
        'source_repo': str(ctx['repo']), 'base_sha': ctx['base'], 'diff': ctx['candidate']['diff'],
        'tests': ctx['candidate']['tests'], 'review_evidence_id': review.json()['evidence_id']})
    assert result.status_code == 200, result.text
    assert all(g['result'] == 'PASS' for g in result.json()['gates']), result.text
    return result.json()['evidence_id']


def _tagged_candidate_head(ctx, run_evidence_id):
    tag = run_evidence_id.lower().replace('ev_', '')[:8] or 'gen'
    ctx['git']('checkout', '--detach', '-q', ctx['patch_head'])
    target = ctx['repo'] / f'tests/evoforge_gen/test_{tag}_1.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(ctx['candidate']['tests'][0]['code'], encoding='utf-8')
    ctx['git']('add', 'tests')
    ctx['git']('commit', '-qm', 'evidence-tagged visible tests')
    return ctx['git']('rev-parse', 'HEAD')


def test_tagged_candidate_registers_matching_server_run_and_remains_immutable(funded, builder_proposal, monkeypatch):
    ctx = builder_proposal
    run_id = _tagged_candidate_run(ctx, monkeypatch)
    head = _tagged_candidate_head(ctx, run_id)
    response = _propose(ctx, head_sha=head, pr_source_evidence_id=run_id)
    assert response.status_code == 200, response.text
    candidate_id = response.json()['candidate_id']
    assert response.json()['pr_source_evidence_id'] == run_id
    assert len(response.json()['pr_source_evidence_sha256']) == 64
    assert _propose(ctx, head_sha=head, pr_source_evidence_id=run_id).json()['candidate_id'] == candidate_id
    assert _propose(ctx, head_sha=head).status_code == 409
    assert _propose(ctx, head_sha=head, pr_source_evidence_id='ev_another_run').status_code == 409
    assert ctx['http'].get(f'/v1/kernel/candidates/{candidate_id}').json()['pr_source_evidence_id'] == run_id
    assert ctx['http'].post('/v1/kernel/merge-authorizations', json={
        'candidate_id': candidate_id, 'head_sha': head, 'policy_hash': '1'*64}).status_code == 409
    with psycopg.connect(funded['dsn'], autocommit=True) as conn:
        ddl = (ROOT/'services/api/migrations/010_candidate_pr_evidence.sql').read_text(encoding='utf-8')
        conn.execute(ddl)
        conn.execute(ddl)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('UPDATE runtime.builder_candidate_evidence SET pr_source_evidence_id=%s '
                         'WHERE candidate_id=%s', ('ev_other', candidate_id))
    assert ctx['http'].get(f'/v1/kernel/candidates/{candidate_id}').json()['pr_source_evidence_id'] == run_id


def test_tagged_candidate_refuses_mismatched_server_run_before_git_or_writes(funded, builder_proposal, monkeypatch):
    from copy import deepcopy
    import main
    ctx = builder_proposal
    valid_id = _tagged_candidate_run(ctx, monkeypatch)
    head = _tagged_candidate_head(ctx, valid_id)
    original = deepcopy(main._evidence[valid_id])
    stub = main._store_evidence({'review': {'stub': True}})
    main._link_stages(stub, ('Review',))
    for problem in ('base', 'diff', 'tests', 'missing_run', 'run_base', 'counts', 'gates', 'review'):
        doc = deepcopy(original)
        doc.pop('id', None)
        if problem == 'base': doc['base_sha'] = 'f'*40
        elif problem == 'diff': doc['diff'] += '\n'
        elif problem == 'tests': doc['tests'][0]['code'] += '\n'
        elif problem == 'missing_run': doc.pop('run')
        elif problem == 'run_base': doc['run']['base'] = 'f'*40
        elif problem == 'counts': doc['run']['visible']['pass'] = 0
        elif problem == 'gates': doc['gates'][0]['result'] = 'FAIL'
        elif problem == 'review': doc['review_evidence_id'] = stub
        bad_id = main._store_evidence(doc)
        main._link_stages(bad_id, ('Candidate', 'Gate'))
        result = _propose(ctx, head_sha=head, pr_source_evidence_id=bad_id)
        assert result.status_code == 409, (problem, result.status_code, result.text)
    missing = _propose(ctx, head_sha=head, pr_source_evidence_id='ev_missing_run')
    assert missing.status_code == 404
    source = deepcopy(main._evidence[ctx['evidence']])
    source.pop('id', None)
    source['mission_id'] = 'mission_other'
    other_source = main._store_evidence(source)
    main._link_stages(other_source, ('Task', 'Candidate', 'Gate'))
    assert _propose(ctx, head_sha=head, evidence_id=other_source, pr_source_evidence_id=valid_id).status_code == 409
    other_project = uuid4()
    with psycopg.connect(funded['dsn'], autocommit=True) as conn:
        conn.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'other')",
                     (funded['scope'].tenant_id, other_project))
    with monkeypatch.context() as foreign:
        foreign.setenv('EVO_PROJECT_ID', str(other_project))
        foreign_run = deepcopy(original)
        foreign_run.pop('id', None)
        foreign_id = main._store_evidence(foreign_run)
        main._link_stages(foreign_id, ('Candidate', 'Gate'))
    assert _propose(ctx, head_sha=head, pr_source_evidence_id=foreign_id).status_code == 404
    assert ctx['clones'] == []
    with funded['kernel']._transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM core.candidates').fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) AS n FROM runtime.builder_candidate_evidence').fetchone()['n'] == 0


def test_tagged_candidate_missing_migration_fails_closed_and_preserves_legacy_binding(funded, builder_proposal):
    ctx = builder_proposal
    registered = _propose(ctx)
    assert registered.status_code == 200, registered.text
    candidate_id = registered.json()['candidate_id']
    with psycopg.connect(funded['dsn'], autocommit=True) as conn:
        conn.execute('ALTER TABLE runtime.builder_candidate_evidence RENAME COLUMN pr_source_evidence_id '
                     'TO pr_source_evidence_id_offline')
        try:
            assert _propose(ctx).status_code == 503
            assert ctx['http'].get(f'/v1/kernel/candidates/{candidate_id}').status_code == 503
        finally:
            conn.execute('ALTER TABLE runtime.builder_candidate_evidence RENAME COLUMN pr_source_evidence_id_offline '
                         'TO pr_source_evidence_id')
    assert _propose(ctx).json()['candidate_id'] == candidate_id
    assert ctx['http'].get(f'/v1/kernel/candidates/{candidate_id}').status_code == 200
