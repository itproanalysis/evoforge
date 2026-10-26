"""Internal, authenticated HTTP bridge to the PostgreSQL Trust Kernel.

One deployment has one server-owned scope. User sessions and model-generated
tenant/project identifiers are not authentication. No model or GitHub calls here.
"""
from __future__ import annotations

from datetime import date
import hmac
import os
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from evoforge.postgres_kernel import (
    BudgetRefused, KernelNotFound, KernelRejected, KernelScope,
    KernelUnavailable, PostgresKernel,
)

router = APIRouter(prefix="/v1/kernel", tags=["internal-kernel"])
bearer = HTTPBearer(auto_error=False)


def authenticated_kernel(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> PostgresKernel:
    expected = os.getenv("EVO_KERNEL_TOKEN", "")
    if len(expected) < 32 or not expected.isascii():
        raise HTTPException(503, "internal kernel authentication is not configured")
    if (credentials is None or credentials.scheme.lower() != "bearer"
            or not hmac.compare_digest(credentials.credentials.encode("utf-8"), expected.encode("utf-8"))):
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


class MergeAuthorizationRequest(InternalRequest):
    candidate_id: UUID
    head_sha: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.post("/reservations")
def reserve(req: ReserveRequest, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return invoke(kernel.reserve_cost, req.call_id, req.period_start, req.amount_micros)


@router.get("/reservations/{call_id}")
def reservation(call_id: UUID, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return invoke(kernel.reservation, call_id)


@router.post("/reservations/{call_id}/sent")
def sent(call_id: UUID, kernel: PostgresKernel = Depends(authenticated_kernel)):
    return invoke(kernel.mark_sent, call_id)


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
