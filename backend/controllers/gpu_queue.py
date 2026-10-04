from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from utils.gpu_queue import (
    QueueTicketError, acquire, cancel, heartbeat, heartbeat_waiting,
    mark_stalled, queue_snapshot, recover_stale_active, release, status,
)

router = APIRouter()


class LeaseRequest(BaseModel):
    claim_id: str = Field(min_length=1, max_length=64)


class ReleaseRequest(LeaseRequest):
    outcome: str = Field(pattern="^(done|failed)$")


class RecoveryRequest(BaseModel):
    confirm_gpu_idle: bool
    reason: str = Field(min_length=8, max_length=300)


async def require_service_key(request: Request) -> None:
    expected = os.getenv("FURNITURE_SERVICE_KEY", "")
    supplied = request.headers.get("X-Service-Key", "")
    if not expected:
        raise HTTPException(503, "GPU queue service authentication is not configured")
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid service credentials")


async def _furniture_ticket(ticket_id: str) -> dict:
    ticket = await status(ticket_id)
    if ticket is None or not str(ticket.get("operation", "")).startswith("furniture:"):
        raise HTTPException(404, "GPU queue ticket not found")
    return ticket


@router.get("/internal/gpu-queue/status", dependencies=[Depends(require_service_key)])
async def get_queue_status():
    return await queue_snapshot()


@router.post("/internal/gpu-queue/{ticket_id}/recover", dependencies=[Depends(require_service_key)])
async def recover_stalled_ticket(ticket_id: str, body: RecoveryRequest):
    if not body.confirm_gpu_idle:
        raise HTTPException(400, "Confirm the GPU is idle before recovering a stalled ticket")
    try:
        await recover_stale_active(ticket_id, body.reason)
    except QueueTicketError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "recovered"}


@router.post("/internal/gpu-queue/{ticket_id}/acquire", dependencies=[Depends(require_service_key)])
async def acquire_ticket(ticket_id: str, body: LeaseRequest):
    await _furniture_ticket(ticket_id)
    try:
        await acquire(ticket_id, body.claim_id)
    except TimeoutError as exc:
        raise HTTPException(504, "Timed out waiting for the shared GPU") from exc
    except QueueTicketError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "acquired"}


@router.post("/internal/gpu-queue/{ticket_id}/waiting-heartbeat", dependencies=[Depends(require_service_key)])
async def waiting_heartbeat_ticket(ticket_id: str):
    await _furniture_ticket(ticket_id)
    return {"waiting": await heartbeat_waiting(ticket_id)}


@router.post("/internal/gpu-queue/{ticket_id}/heartbeat", dependencies=[Depends(require_service_key)])
async def heartbeat_ticket(ticket_id: str, body: LeaseRequest):
    await _furniture_ticket(ticket_id)
    try:
        await heartbeat(ticket_id, body.claim_id)
    except QueueTicketError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "active"}


@router.post("/internal/gpu-queue/{ticket_id}/release", dependencies=[Depends(require_service_key)])
async def release_ticket(ticket_id: str, body: ReleaseRequest):
    await _furniture_ticket(ticket_id)
    try:
        await release(ticket_id, body.claim_id, body.outcome)
    except QueueTicketError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": body.outcome}


@router.post("/internal/gpu-queue/{ticket_id}/stalled", dependencies=[Depends(require_service_key)])
async def stall_ticket(ticket_id: str, body: LeaseRequest, reason: str = "upstream state unknown"):
    await _furniture_ticket(ticket_id)
    try:
        await mark_stalled(ticket_id, body.claim_id, reason)
    except QueueTicketError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "stalled"}


@router.delete("/internal/gpu-queue/{ticket_id}", dependencies=[Depends(require_service_key)])
async def cancel_ticket(ticket_id: str):
    await _furniture_ticket(ticket_id)
    if not await cancel(ticket_id, "cancelled"):
        raise HTTPException(409, "GPU queue ticket is already active or finished")
    return {"status": "cancelled"}
