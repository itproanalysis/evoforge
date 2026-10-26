"""Live PostgreSQL acceptance checks; EVO_TEST_DATABASE_URL must be a disposable server.

The fixture refuses existing kernel roles and creates/drops only its own database.
No provider calls, billing API, production DATABASE_URL, or model keys are used.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import os
from pathlib import Path
import sys
from uuid import uuid4

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
    BudgetRefused, KernelRejected, KernelScope, PostgresKernel, cents_to_micros,
)

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
