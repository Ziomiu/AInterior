"""Client for the backend's cross-process GPU admission queue."""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from contextlib import contextmanager
from typing import Iterator

import requests
from fastapi import HTTPException, Request

from app.config import settings

logger = logging.getLogger(__name__)


def ticket_id_from_request(request: Request) -> str | None:
    ticket_id = request.headers.get("X-GPU-Ticket", "")
    if not settings.gpu_queue_url:
        if ticket_id:
            raise HTTPException(503, "A GPU queue ticket was supplied but the shared queue is not configured")
        return None
    if not ticket_id or len(ticket_id) > 64:
        raise HTTPException(503, "A shared GPU queue ticket is required")
    return ticket_id


def _request(
    action: str,
    ticket_id: str,
    claim_id: str | None = None,
    outcome: str | None = None,
) -> dict | None:
    if not settings.gpu_queue_url:
        return
    url = f"{settings.gpu_queue_url.rstrip('/')}/{ticket_id}"
    method = "DELETE" if action == "cancel" else "POST"
    if action != "cancel":
        url = f"{url}/{action}"
    body = {"claim_id": claim_id} if claim_id is not None else None
    if outcome is not None:
        body["outcome"] = outcome
    timeout = settings.gpu_queue_acquire_timeout_seconds + 30 if action == "acquire" else 10
    response = requests.request(
        method,
        url,
        headers={"X-Service-Key": settings.service_api_key or ""},
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json() if response.content else None


def _heartbeat_loop(ticket_id: str, claim_id: str, stop: threading.Event) -> None:
    while not stop.wait(settings.gpu_queue_heartbeat_seconds):
        try:
            _request("heartbeat", ticket_id, claim_id)
        except requests.RequestException as exc:
            logger.warning("Shared GPU queue heartbeat failed for ticket %s; retrying: %s", ticket_id, exc)


@contextmanager
def gpu_slot(ticket_id: str | None) -> Iterator[None]:
    if ticket_id is None:
        yield
        return

    claim_id = uuid.uuid4().hex
    _request("acquire", ticket_id, claim_id)
    stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(ticket_id, claim_id, stop), daemon=True,
    )
    heartbeat.start()
    outcome = "failed"
    try:
        yield
        outcome = "done"
    finally:
        stop.set()
        heartbeat.join(timeout=2)
        _request("release", ticket_id, claim_id, outcome)


async def acquire_job_ticket(ticket_id: str, claim_id: str) -> None:
    await asyncio.to_thread(_request, "acquire", ticket_id, claim_id)


async def heartbeat_waiting_job_ticket(ticket_id: str) -> bool:
    response = await asyncio.to_thread(_request, "waiting-heartbeat", ticket_id)
    return bool(response and response.get("waiting"))


async def heartbeat_job_ticket(ticket_id: str, claim_id: str) -> None:
    await asyncio.to_thread(_request, "heartbeat", ticket_id, claim_id)


async def release_job_ticket(ticket_id: str, claim_id: str, outcome: str) -> None:
    await asyncio.to_thread(_request, "release", ticket_id, claim_id, outcome)


async def cancel_job_ticket(ticket_id: str) -> None:
    await asyncio.to_thread(_request, "cancel", ticket_id)
