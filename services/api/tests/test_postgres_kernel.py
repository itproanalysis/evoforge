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
