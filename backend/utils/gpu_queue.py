"""Mongo-backed, cross-process admission queue for the shared GPU."""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from database.mongo import db
from utils.gpu_queue_policy import fair_ticket_order, stale_ticket_ids

_STATE_ID = "shared-gpu"
_POLL_INTERVAL_SECONDS = 0.25
_MAX_WAITING = int(os.getenv("GPU_QUEUE_MAX_WAITING", "20"))
_MAX_WAITING_PER_USER = int(os.getenv("GPU_QUEUE_MAX_WAITING_PER_USER", "1"))
_ACQUIRE_TIMEOUT_SECONDS = float(os.getenv("GPU_QUEUE_ACQUIRE_TIMEOUT_SECONDS", "900"))
_WAITING_HEARTBEAT_INTERVAL_SECONDS = max(
    1.0, float(os.getenv("GPU_QUEUE_WAITING_HEARTBEAT_SECONDS", "10"))
)
_WAITING_STALE_SECONDS = max(
    _WAITING_HEARTBEAT_INTERVAL_SECONDS * 3,
    float(os.getenv("GPU_QUEUE_WAITING_STALE_SECONDS", "90")),
)
_ACTIVE_STALE_SECONDS = max(
    _WAITING_STALE_SECONDS,
    float(os.getenv("GPU_QUEUE_ACTIVE_STALE_SECONDS", "90")),
)
_HISTORY_SIZE = 100
_state = db["gpu_queue_state"]


class QueueFullError(Exception):
    """Raised when the shared queue or a user's waiting allowance is full."""


class QueueTicketError(Exception):
    """Raised when a ticket cannot be acquired or updated."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_state() -> None:
    try:
        await _state.update_one(
            {"_id": _STATE_ID},
            {"$setOnInsert": {"queue": [], "active": None, "last_user_id": None, "history": []}},
            upsert=True,
        )
    except DuplicateKeyError:
        # Another API worker initialized the singleton concurrently.
        pass


async def _reap_stale_waiters(now: datetime | None = None) -> None:
    now = now or _now()
    cutoff = now - timedelta(seconds=_WAITING_STALE_SECONDS)
    state = await _state.find_one({"_id": _STATE_ID}, {"queue": 1})
    if state is None:
        return
    stale_ids = stale_ticket_ids(state.get("queue", []), cutoff)
    if not stale_ids:
        return
    await _state.update_one(
        {"_id": _STATE_ID},
        {
            "$pull": {
                "queue": {
                    "ticket_id": {"$in": stale_ids},
                    "$or": [
                        {"heartbeat_at": {"$lt": cutoff}},
                        {"heartbeat_at": None, "created_at": {"$lt": cutoff}},
                    ],
                }
            },
            "$set": {"updated_at": now},
        },
    )


async def enqueue(user_id: str, operation: str) -> str:
    await _ensure_state()
    await _reap_stale_waiters()
    ticket_id = uuid4().hex
    now = _now()
    item = {
        "ticket_id": ticket_id,
        "user_id": str(user_id),
        "operation": operation,
        "created_at": now,
        "heartbeat_at": now,
    }
    filter_query = {
        "_id": _STATE_ID,
        "$expr": {
            "$and": [
                {"$lt": [{"$size": "$queue"}, _MAX_WAITING]},
                {
                    "$lt": [
                        {
                            "$size": {
                                "$filter": {
                                    "input": "$queue",
                                    "as": "item",
                                    "cond": {"$eq": ["$$item.user_id", str(user_id)]},
                                }
                            }
                        },
                        _MAX_WAITING_PER_USER,
                    ]
                },
            ]
        },
    }
    state = await _state.find_one_and_update(
        filter_query,
        {"$push": {"queue": item}, "$set": {"updated_at": _now()}},
        return_document=ReturnDocument.AFTER,
    )
    if state is None:
        snapshot = await _state.find_one({"_id": _STATE_ID}, {"queue": 1}) or {}
        waiting = snapshot.get("queue", [])
        if len(waiting) >= _MAX_WAITING:
            raise QueueFullError("The shared GPU queue is full")
        raise QueueFullError("You already have a job waiting for the GPU")
    return ticket_id


async def status(ticket_id: str) -> dict[str, Any] | None:
    state = await _state.find_one({"_id": _STATE_ID})
    if state is None:
        return None
    for item in state.get("queue", []):
        if item["ticket_id"] == ticket_id:
            order = fair_ticket_order(state["queue"], state.get("last_user_id"))
            return {**item, "status": "queued", "queue_position": order.index(ticket_id) + 1}
    active = state.get("active")
    if active and active["ticket_id"] == ticket_id:
        return {**active, "status": "running", "queue_position": 0}
    for item in state.get("history", []):
        if item["ticket_id"] == ticket_id:
            return item
    return None


async def acquire(
    ticket_id: str,
    claim_id: str,
    timeout_seconds: float | None = _ACQUIRE_TIMEOUT_SECONDS,
) -> None:
    started = time.monotonic()
    await _reap_stale_waiters()
    last_liveness_update = time.monotonic()
    while True:
        now_monotonic = time.monotonic()
        if now_monotonic - last_liveness_update >= _WAITING_HEARTBEAT_INTERVAL_SECONDS:
            await _reap_stale_waiters()
            if not await heartbeat_waiting(ticket_id):
                raise QueueTicketError("GPU queue ticket expired while waiting")
            last_liveness_update = now_monotonic
        state = await _state.find_one({"_id": _STATE_ID})
        if state is None:
            raise QueueTicketError("GPU queue is not initialized")
        active = state.get("active")
        if active and active.get("ticket_id") == ticket_id and active.get("claim_id") == claim_id:
            return
        if not any(item["ticket_id"] == ticket_id for item in state.get("queue", [])):
            raise QueueTicketError("GPU queue ticket is no longer waiting")
        first = fair_ticket_order(state["queue"], state.get("last_user_id"))[0]
        if active is None and first == ticket_id:
            item = next(item for item in state["queue"] if item["ticket_id"] == ticket_id)
            acquired_at = _now()
            updated = await _state.find_one_and_update(
                {"_id": _STATE_ID, "active": None, "queue.ticket_id": ticket_id},
                {
                    "$pull": {"queue": {"ticket_id": ticket_id}},
                    "$set": {
                        "active": {
                            **item, "claim_id": claim_id, "started_at": acquired_at,
                            "heartbeat_at": acquired_at, "status": "running",
                        },
                        "last_user_id": item["user_id"],
                        "updated_at": acquired_at,
                    },
                },
                return_document=ReturnDocument.AFTER,
            )
            if updated and updated.get("active", {}).get("ticket_id") == ticket_id:
                return
        if timeout_seconds is not None and time.monotonic() - started >= timeout_seconds:
            await cancel(ticket_id, "queue_wait_timeout")
            raise TimeoutError("Timed out waiting for the shared GPU queue")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def heartbeat(ticket_id: str, claim_id: str) -> None:
    now = _now()
    result = await _state.update_one(
        {"_id": _STATE_ID, "active.ticket_id": ticket_id, "active.claim_id": claim_id},
        {"$set": {"active.heartbeat_at": now, "updated_at": now}},
    )
    if not result.matched_count:
        raise QueueTicketError("GPU queue lease is no longer active")


async def heartbeat_waiting(ticket_id: str) -> bool:
    now = _now()
    result = await _state.update_one(
        {"_id": _STATE_ID, "queue.ticket_id": ticket_id},
        {"$set": {"queue.$.heartbeat_at": now, "updated_at": now}},
    )
    return bool(result.matched_count)


async def release(ticket_id: str, claim_id: str, outcome: str = "done") -> None:
    now = _now()
    state = await _state.find_one({
        "_id": _STATE_ID, "active.ticket_id": ticket_id, "active.claim_id": claim_id,
    })
    if state is None:
        existing = await status(ticket_id)
        if existing is not None and existing.get("status") in {"done", "failed", "cancelled"}:
            return
        raise QueueTicketError("GPU queue lease is not owned by this claim")
    active = state["active"]
    history_item = {**active, "status": outcome, "finished_at": now}
    await _state.update_one(
        {"_id": _STATE_ID, "active.ticket_id": ticket_id, "active.claim_id": claim_id},
        {
            "$set": {"active": None, "updated_at": now},
            "$push": {"history": {"$each": [history_item], "$slice": -_HISTORY_SIZE}},
        },
    )


async def mark_stalled(ticket_id: str, claim_id: str, reason: str) -> None:
    now = _now()
    result = await _state.update_one(
        {"_id": _STATE_ID, "active.ticket_id": ticket_id, "active.claim_id": claim_id},
        {"$set": {
            "active.status": "stalled",
            "active.stalled_reason": reason[:300],
            "active.heartbeat_at": now,
            "updated_at": now,
        }},
    )
    if not result.matched_count:
        raise QueueTicketError("GPU queue lease is no longer active")


async def recover_stale_active(ticket_id: str, reason: str) -> None:
    now = _now()
    cutoff = now - timedelta(seconds=_ACTIVE_STALE_SECONDS)
    state = await _state.find_one({"_id": _STATE_ID, "active.ticket_id": ticket_id})
    if state is None:
        raise QueueTicketError("GPU queue ticket is not active")
    active = state["active"]
    history_item = {
        **active,
        "status": "failed",
        "finished_at": now,
        "recovery_reason": reason[:300],
    }
    result = await _state.update_one(
        {
            "_id": _STATE_ID,
            "active.ticket_id": ticket_id,
            "active.claim_id": active["claim_id"],
            "active.heartbeat_at": {"$lt": cutoff},
        },
        {
            "$set": {"active": None, "updated_at": now},
            "$push": {"history": {"$each": [history_item], "$slice": -_HISTORY_SIZE}},
        },
    )
    if not result.matched_count:
        raise QueueTicketError("GPU queue lease still has a recent heartbeat")


async def cancel(ticket_id: str, outcome: str = "cancelled") -> bool:
    state = await _state.find_one({"_id": _STATE_ID, "queue.ticket_id": ticket_id})
    if state is None:
        return False
    item = next(item for item in state["queue"] if item["ticket_id"] == ticket_id)
    now = _now()
    result = await _state.update_one(
        {"_id": _STATE_ID, "queue.ticket_id": ticket_id},
        {
            "$pull": {"queue": {"ticket_id": ticket_id}},
            "$set": {"updated_at": now},
            "$push": {"history": {"$each": [{**item, "status": outcome, "finished_at": now}], "$slice": -_HISTORY_SIZE}},
        },
    )
    return bool(result.modified_count)


async def queue_snapshot() -> dict[str, Any]:
    await _ensure_state()
    state = await _state.find_one({"_id": _STATE_ID})
    queue = state.get("queue", [])
    order = fair_ticket_order(queue, state.get("last_user_id"))
    waiting_by_id = {item["ticket_id"]: item for item in queue}
    return {
        "active": state.get("active"),
        "queue": [
            {**waiting_by_id[ticket_id], "queue_position": position}
            for position, ticket_id in enumerate(order, 1)
        ],
        "queue_limit": _MAX_WAITING,
    }