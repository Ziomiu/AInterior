import unittest
from datetime import datetime, timedelta, timezone

from utils.gpu_queue_policy import fair_ticket_order, stale_ticket_ids


class FairTicketOrderTests(unittest.TestCase):
    def test_round_robins_users_and_preserves_each_users_order(self):
        queue = [
            {"ticket_id": "a1", "user_id": "alice"},
            {"ticket_id": "a2", "user_id": "alice"},
            {"ticket_id": "b1", "user_id": "bob"},
            {"ticket_id": "c1", "user_id": "carol"},
        ]

        self.assertEqual(fair_ticket_order(queue, None), ["a1", "b1", "c1", "a2"])

    def test_continues_after_the_last_served_user(self):
        queue = [
            {"ticket_id": "a1", "user_id": "alice"},
            {"ticket_id": "a2", "user_id": "alice"},
            {"ticket_id": "b1", "user_id": "bob"},
            {"ticket_id": "c1", "user_id": "carol"},
        ]

        self.assertEqual(fair_ticket_order(queue, "alice"), ["b1", "c1", "a1", "a2"])

    def test_keeps_fifo_when_only_one_user_is_waiting(self):
        queue = [
            {"ticket_id": "a1", "user_id": "alice"},
            {"ticket_id": "a2", "user_id": "alice"},
        ]

        self.assertEqual(fair_ticket_order(queue, "alice"), ["a1", "a2"])


class StaleTicketTests(unittest.TestCase):
    def test_expires_only_tickets_without_a_recent_heartbeat(self):
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=90)
        queue = [
            {"ticket_id": "abandoned", "created_at": cutoff - timedelta(seconds=1)},
            {"ticket_id": "alive", "created_at": cutoff - timedelta(minutes=5), "heartbeat_at": now},
            {
                "ticket_id": "mongo-naive-date",
                "created_at": (cutoff - timedelta(seconds=1)).replace(tzinfo=None),
            },
        ]

        self.assertEqual(stale_ticket_ids(queue, cutoff), ["abandoned", "mongo-naive-date"])


if __name__ == "__main__":
    unittest.main()