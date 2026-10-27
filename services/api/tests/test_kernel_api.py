"""Internal API authentication, trusted scope, validation and failure mapping."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import app  # noqa: E402
from evoforge import kernel_api  # noqa: E402
from evoforge.postgres_kernel import (  # noqa: E402
    BudgetRefused, KernelNotFound, KernelRejected, KernelUnavailable, ReservationState,
)

TOKEN = "test-only-kernel-service-token-not-a-real-secret"


@pytest.fixture
def api(monkeypatch):
    tenant, project, call = uuid4(), uuid4(), uuid4()
    monkeypatch.setenv("EVO_KERNEL_TOKEN", TOKEN)
    monkeypatch.setenv("EVO_TENANT_ID", str(tenant))
    monkeypatch.setenv("EVO_PROJECT_ID", str(project))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused.invalid/test")
    state = ReservationState(call, date(2026, 10, 1), 100, None, "RESERVED", "RESERVED")
    kernel = Mock()
    kernel.reserve_cost.return_value = state
    kernel.reservation.return_value = state
    factory = Mock(return_value=kernel)
    monkeypatch.setattr(kernel_api, "PostgresKernel", factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield {"client": client, "factory": factory, "kernel": kernel,
               "tenant": tenant, "project": project, "call": call,
               "headers": {"Authorization": f"Bearer {TOKEN}"},
               "body": {"call_id": str(call), "period_start": "2026-10-01", "amount_micros": 100}}


def test_scope_comes_from_server_and_money_is_passed_as_integer_micros(api):
    response = api["client"].post("/v1/kernel/reservations", headers=api["headers"], json=api["body"])
    assert response.status_code == 200
    assert response.json()["reserved_micros"] == 100
    scope = api["factory"].call_args.args[1]
    assert scope.tenant_id == api["tenant"] and scope.project_id == api["project"]
    api["kernel"].reserve_cost.assert_called_once_with(api["call"], date(2026, 10, 1), 100)


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-token", "Basic wrong-token"])
def test_unauthenticated_requests_cannot_create_database_adapter(api, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    response = api["client"].post("/v1/kernel/reservations", headers=headers, json=api["body"])
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    api["factory"].assert_not_called()
    assert TOKEN not in response.text


def test_runner_evidence_ingestion_and_reads_require_the_internal_service_credential(api):
    candidate=uuid4()
    body={'candidate_id':str(candidate),'call_id':str(api['call']),'evidence_id':'ev_private'}
    for authorization in (None,'Bearer wrong-token','Basic wrong-token'):
        headers={'Authorization':authorization} if authorization else {}
        writes=api['client'].post('/v1/kernel/candidate-runs',json=body,headers=headers)
        reads=api['client'].get(f'/v1/kernel/candidates/{candidate}/runner-evidence/ev_private',headers=headers)
        assert writes.status_code==reads.status_code==401
        assert writes.headers['www-authenticate']==reads.headers['www-authenticate']=='Bearer'
        assert TOKEN not in writes.text+reads.text
    api['factory'].assert_not_called()


def test_canonical_command_lifecycle_requires_service_auth_before_creating_adapter(api):
    cid='cmd_'+uuid4().hex
    client=api['client']
    responses=[client.post('/v1/kernel/commands',json={'goal':'g','idempotency_key':'k'}),
               client.get('/v1/kernel/commands/'+cid),
               client.post('/v1/kernel/commands/'+cid+'/dispatch',json={}),
               client.post('/v1/kernel/commands/'+cid+'/complete',json={'response':{'command_id':cid}})]
    assert all(r.status_code==401 and TOKEN not in r.text for r in responses)
    api['factory'].assert_not_called()


@pytest.mark.parametrize("missing", ["EVO_TENANT_ID", "EVO_PROJECT_ID", "DATABASE_URL", "EVO_KERNEL_TOKEN"])
def test_missing_server_configuration_fails_closed(api, monkeypatch, missing):
    monkeypatch.delenv(missing, raising=False)
    # The fake factory is intentionally replaced for constructor validation.
    from evoforge.postgres_kernel import PostgresKernel
    monkeypatch.setattr(kernel_api, "PostgresKernel", PostgresKernel)
    response = api["client"].post("/v1/kernel/reservations", headers=api["headers"], json=api["body"])
    assert response.status_code == 503


@pytest.mark.parametrize("field", ["tenant_id", "project_id", "dsn"])
def test_request_cannot_override_server_scope_or_connection(api, field):
    response = api["client"].post("/v1/kernel/reservations", headers=api["headers"],
                                  json={**api["body"], field: str(uuid4())})
    assert response.status_code == 422
    api["kernel"].reserve_cost.assert_not_called()


@pytest.mark.parametrize("amount", [True, 1.0, "100", 0, -1, 2**63])
def test_micros_are_strict_positive_int64(api, amount):
    response = api["client"].post("/v1/kernel/reservations", headers=api["headers"],
                                  json={**api["body"], "amount_micros": amount})
    assert response.status_code == 422
    api["kernel"].reserve_cost.assert_not_called()


@pytest.mark.parametrize("error, expected", [
    (BudgetRefused, 402), (KernelNotFound, 404), (KernelRejected, 409), (KernelUnavailable, 503),
])
def test_database_failures_are_not_success_or_credential_leaks(api, error, expected):
    marker = "private-database-credential-must-not-leak"
    api["kernel"].reserve_cost.side_effect = error(marker)
    response = api["client"].post("/v1/kernel/reservations", headers=api["headers"], json=api["body"])
    assert response.status_code == expected
    assert marker not in response.text and TOKEN not in response.text


def test_unknown_reservation_and_foreign_scope_have_same_response(api):
    api["kernel"].reservation.side_effect = KernelNotFound("not in scope")
    response = api["client"].get(f"/v1/kernel/reservations/{api['call']}", headers=api["headers"])
    assert response.status_code == 404 and response.json()["detail"] == "resource not found in scope"


def test_merge_authorization_returns_only_server_checked_head(api):
    response = api["client"].post("/v1/kernel/merge-authorizations", headers=api["headers"], json={
        "candidate_id": str(api["call"]), "head_sha": "a" * 40, "policy_hash": "1" * 64})
    assert response.status_code == 200
    api["kernel"].authorize_merge.assert_called_once_with(api["call"], "a" * 40, "1" * 64)
    assert response.json()["authorized"] is True


def test_receipt_uses_same_authentication_and_does_not_accept_an_amount_override(api):
    from receipt_fixtures import receipt_document
    document = receipt_document(tenant=api['tenant'], project=api['project'])
    rid = document['receipt_id']
    api['kernel'].record_receipt.return_value = {**document, 'ledger_entry_id': None}
    api['kernel'].receipt_document.return_value = {**document, 'ledger_entry_id': None}
    api['kernel'].settle_from_receipt.return_value = api['kernel'].reservation.return_value
    unauthenticated = api['client'].post('/v1/kernel/receipts', json=document)
    assert unauthenticated.status_code == 401
    api['kernel'].record_receipt.assert_not_called()
    response = api['client'].post('/v1/kernel/receipts', json=document, headers=api['headers'])
    assert response.status_code == 200 and response.json()['ledger_entry_id'] is None
    api['kernel'].record_receipt.assert_called_once_with(document)
    assert api['client'].get(f'/v1/kernel/receipts/{rid}', headers=api['headers']).status_code == 200
    api['kernel'].receipt_document.assert_called_once_with(UUID(rid))
    overridden = api['client'].post(f'/v1/kernel/receipts/{rid}/settle', headers=api['headers'],
                                    json={'customer_micros': 1, 'tenant_id': str(uuid4())})
    assert overridden.status_code == 422
    api['kernel'].settle_from_receipt.assert_not_called()
    assert api['client'].post(f'/v1/kernel/receipts/{rid}/settle', headers=api['headers'], json={}).status_code == 200
    api['kernel'].settle_from_receipt.assert_called_once_with(UUID(rid))


def test_invalid_receipt_returns_sanitized_422(api):
    from evoforge.postgres_receipts import ReceiptInvalid
    api['kernel'].record_receipt.side_effect = ReceiptInvalid('must-not-leak-provider-or-token-data')
    response = api['client'].post('/v1/kernel/receipts', json={'bad': 'must-not-leak'}, headers=api['headers'])
    assert response.status_code == 422 and 'must-not-leak' not in response.text


def test_builder_preparation_uses_only_server_model_and_price_version(api, monkeypatch):
    monkeypatch.setenv('EVO_PRICE_TABLE_VERSION', 'approved-v1')
    monkeypatch.setenv('MODEL_BUILDER', 'muse-spark-1.3')
    packet = uuid4()
    body = {**api['body'], 'packet_id': str(packet)}
    api['kernel'].prepare_builder_call.return_value = {'model': 'muse-spark-1.3'}
    response = api['client'].post('/v1/kernel/builder-calls', headers=api['headers'], json=body)
    assert response.status_code == 200
    api['kernel'].prepare_builder_call.assert_called_once_with(api['call'], date(2026, 10, 1), 100,
                                                              packet, 'approved-v1', 'muse-spark-1.3')


@pytest.mark.parametrize('override', ['model', 'provider', 'price_table_version', 'tenant_id', 'project_id'])
def test_builder_request_cannot_choose_its_model_price_or_scope(api, monkeypatch, override):
    monkeypatch.setenv('EVO_PRICE_TABLE_VERSION', 'approved-v1')
    response = api['client'].post('/v1/kernel/builder-calls', headers=api['headers'], json={
        **api['body'], 'packet_id': str(uuid4()), override: 'forged'})
    assert response.status_code == 422
    api['kernel'].prepare_builder_call.assert_not_called()


def test_missing_builder_price_configuration_does_not_reserve(api, monkeypatch):
    monkeypatch.delenv('EVO_PRICE_TABLE_VERSION', raising=False)
    response = api['client'].post('/v1/kernel/builder-calls', headers=api['headers'], json={
        **api['body'], 'packet_id': str(uuid4())})
    assert response.status_code == 503
    api['kernel'].prepare_builder_call.assert_not_called()
