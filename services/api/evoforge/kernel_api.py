"""Internal, authenticated HTTP bridge to the PostgreSQL Trust Kernel.

One deployment has one server-owned scope. User sessions and model-generated
tenant/project identifiers are not authentication. No model or GitHub calls here.
"""
from __future__ import annotations

from datetime import date
import hmac
import os
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from evoforge.commands import NeedsConfirmation, TransitionError

from evoforge.postgres_kernel import (
    BudgetRefused, KernelNotFound, KernelRejected, KernelScope,
    KernelUnavailable, PostgresKernel,
)

router = APIRouter(prefix="/v1/kernel", tags=["internal-kernel"])
bearer = HTTPBearer(auto_error=False)


def authenticated_kernel(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                         service_token: str | None = Header(default=None,alias='X-Evoforge-Kernel-Token')) -> PostgresKernel:
    expected = os.getenv("EVO_KERNEL_TOKEN", "")
    if len(expected) < 32 or not expected.isascii():
        raise HTTPException(503, "internal kernel authentication is not configured")
    # Google IAM/application ID authentication keeps Authorization. The private
    # kernel credential is independent; an invalid explicit header never falls
    # back to another credential. Legacy local Bearer use remains compatible.
    supplied=service_token
    if supplied is None and credentials is not None and credentials.scheme.lower()=='bearer':
        supplied=credentials.credentials
    if (supplied is None or not hmac.compare_digest(supplied.encode('utf-8'),expected.encode('utf-8'))):
        raise HTTPException(401, "internal kernel authentication required", headers={"WWW-Authenticate": "Bearer"})
    dsn = os.getenv("DATABASE_URL", "")
    try:
        scope = KernelScope(UUID(os.getenv("EVO_TENANT_ID", "")), UUID(os.getenv("EVO_PROJECT_ID", "")))
        return PostgresKernel(dsn, scope)
    except ValueError:
        raise HTTPException(503, "internal kernel database scope is not configured") from None


def invoke(operation, *args):
    try:
        return operation(*args)
    except BudgetRefused:
        raise HTTPException(402, "budget or prepaid credit refused reservation") from None
    except KernelNotFound:
        raise HTTPException(404, "resource not found in scope") from None
    except KernelRejected:
        raise HTTPException(409, "Trust Kernel rejected the operation") from None
    except KernelUnavailable:
        raise HTTPException(503, "PostgreSQL Trust Kernel unavailable") from None
    except NeedsConfirmation:
        raise HTTPException(409, 'command requires confirmation') from None
    except TransitionError:
        raise HTTPException(409, 'canonical command transition refused') from None
    except ValueError:
        raise HTTPException(422, "invalid kernel operation parameters") from None


class InternalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReserveRequest(InternalRequest):
    call_id: UUID
    period_start: date
    amount_micros: StrictInt = Field(gt=0, le=2**63 - 1)


class SettleRequest(InternalRequest):
    receipt_id: UUID
    customer_micros: StrictInt = Field(gt=0, le=2**63 - 1)


class BuilderCallRequest(ReserveRequest):
    packet_id: UUID


def builder_configuration():
    from evoforge.postgres_builder import identity
    try:
        return (identity(os.getenv("EVO_PRICE_TABLE_VERSION", "")),
                identity(os.getenv("MODEL_BUILDER", "muse-spark-1.3")))
    except ValueError:
        raise HTTPException(503, "Builder price version or model is not configured") from None


class MergeAuthorizationRequest(InternalRequest):
    candidate_id: UUID
    head_sha: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class CandidateRunRequest(InternalRequest):
    candidate_id: UUID
    call_id: UUID
    evidence_id: str = Field(min_length=1, max_length=256)


class CommandRequest(InternalRequest):
    goal: str = Field(min_length=1,max_length=100000)
    idempotency_key: str = Field(min_length=1,max_length=4096)
    risk: Literal['LOW','MEDIUM','HIGH','CRITICAL'] = 'LOW'
    confirm: StrictBool = False
    expected_version: StrictInt | None = Field(default=None,ge=0,le=2**63-1)


class CommandResponseRequest(InternalRequest):
    response: dict


def existing_command(kernel,command_id):
    from evoforge.postgres_commands import CommandStore
    store=CommandStore(kernel)
    command=invoke(store.get,command_id)
    if command is None:
        raise HTTPException(404,'resource not found in scope')
    return store,command


@router.post('/commands')
def accept_command(req: CommandRequest, kernel: PostgresKernel = Depends(authenticated_kernel)):
    from evoforge.postgres_commands import CommandStore
    # This is BUILD/ASK acceptance only, never a structured approval shortcut.
    return invoke(CommandStore(kernel).create,req.goal,req.idempotency_key,'BUILD',req.risk,
                  req.confirm,req.expected_version)


@router.get('/commands/{command_id}')
def command(command_id: str, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return existing_command(kernel,command_id)[1]


@router.post('/commands/{command_id}/dispatch')
def dispatch_command(command_id: str, req: InternalRequest,
                     kernel: PostgresKernel = Depends(authenticated_kernel)):
    store,_=existing_command(kernel,command_id)
    return invoke(store.dispatch,command_id)


@router.post('/commands/{command_id}/complete')
def complete_command(command_id: str, req: CommandResponseRequest,
                     kernel: PostgresKernel = Depends(authenticated_kernel)):
    store,_=existing_command(kernel,command_id)
    return invoke(store.complete,command_id,req.response)


@router.post("/reservations")
def reserve(req: ReserveRequest, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return invoke(kernel.reserve_cost, req.call_id, req.period_start, req.amount_micros)


@router.get("/reservations/{call_id}")
def reservation(call_id: UUID, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return invoke(kernel.reservation, call_id)


@router.post("/reservations/{call_id}/sent")
def sent(call_id: UUID, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return invoke(kernel.mark_sent, call_id, os.getenv("MODEL_BUILDER", "muse-spark-1.3"))


@router.post("/reservations/{call_id}/unknown")
def unknown(call_id: UUID, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return invoke(kernel.mark_unknown, call_id)


@router.post("/reservations/{call_id}/release-not-accepted")
def release(call_id: UUID, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return invoke(kernel.release_not_accepted, call_id)


@router.post("/reservations/{call_id}/settle")
def settle(call_id: UUID, req: SettleRequest, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return invoke(kernel.settle_reservation, call_id, req.receipt_id, req.customer_micros)


@router.post("/merge-authorizations")
def authorize(req: MergeAuthorizationRequest, kernel: PostgresKernel = Depends(authenticated_kernel)):
    invoke(kernel.authorize_merge, req.candidate_id, req.head_sha, req.policy_hash)
    return {"authorized": True, "candidate_id": req.candidate_id,
            "head_sha": req.head_sha, "policy_hash": req.policy_hash}


@router.post("/receipts")
def record_receipt(document: dict = Body(...), kernel: PostgresKernel = Depends(authenticated_kernel)):
    # Trusted Broker/reconciler only. A valid document is not proof of a bill;
    # model JSON and browser clients must not receive this service credential.
    return invoke(kernel.record_receipt, document)


@router.get("/receipts/{receipt_id}")
def receipt(receipt_id: UUID, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return invoke(kernel.receipt_document, receipt_id)


@router.post("/receipts/{receipt_id}/settle")
def settle_receipt(receipt_id: UUID, req: InternalRequest,
                   kernel: PostgresKernel = Depends(authenticated_kernel)):
    # An empty object is required so amount/scope overrides are rejected.
    return invoke(kernel.settle_from_receipt, receipt_id)


@router.post("/builder-calls")
def prepare_builder_call(req: BuilderCallRequest, kernel: PostgresKernel = Depends(authenticated_kernel)):
    price_version, model = builder_configuration()
    return invoke(kernel.prepare_builder_call, req.call_id, req.period_start, req.amount_micros,
                  req.packet_id, price_version, model)


@router.get("/builder-calls/{call_id}")
def builder_call(call_id: UUID, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return invoke(kernel.builder_call, call_id)


@router.post('/candidate-runs')
def candidate_run(req: CandidateRunRequest, kernel: PostgresKernel = Depends(authenticated_kernel)):
    from evoforge.postgres_run_evidence import record
    return invoke(record,kernel,req.candidate_id,req.call_id,req.evidence_id)


@router.get('/candidates/{candidate_id}/runner-evidence/{evidence_id}')
def candidate_run_evidence(candidate_id: UUID, evidence_id: str,
                           kernel: PostgresKernel = Depends(authenticated_kernel)):
    from evoforge.postgres_run_evidence import read
    return invoke(read,kernel,candidate_id,evidence_id)
