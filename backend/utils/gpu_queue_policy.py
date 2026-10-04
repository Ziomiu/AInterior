"""Pure scheduling policy for the shared GPU queue."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def fair_ticket_order(queue: list[dict[str, Any]], last_user_id: str | None) -> list[str]:
    """Round-robin users while preserving each user's submission order."""
    by_user: dict[str, list[str]] = {}
    for item in queue:
        by_user.setdefault(str(item["user_id"]), []).append(item["ticket_id"])

    ordered: list[str] = []
    users = list(by_user)
    total_tickets = sum(len(tickets) for tickets in by_user.values())
    previous_user = last_user_id
    while len(ordered) < total_tickets:
        start = (users.index(previous_user) + 1) % len(users) if previous_user in by_user else 0
        for offset in range(len(users)):
            user_id = users[(start + offset) % len(users)]
            if by_user[user_id]:
                ordered.append(by_user[user_id].pop(0))
                previous_user = user_id
                break
    return ordered


def stale_ticket_ids(queue: list[dict[str, Any]], cutoff: datetime) -> list[str]:
    """Find queued tickets whose owner stopped sending liveness heartbeats."""
    stale = []
    for item in queue:
        last_seen = item.get("heartbeat_at") or item.get("created_at")
        if last_seen is not None:
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if last_seen < cutoff:
                stale.append(item["ticket_id"])
    return stale