import asyncio
from datetime import timedelta
import os
import unittest
from unittest.mock import patch

from utils import gpu_queue


_TEST_DATABASE = os.getenv("GPU_QUEUE_MONGO_TEST_DATABASE", "")
_CONFIGURED_DATABASE = os.getenv("MONGO_DATABASE", "")


@unittest.skipUnless(
    _TEST_DATABASE.startswith("ainterior_gpu_queue_test_")
    and _TEST_DATABASE == _CONFIGURED_DATABASE,
    "Set MONGO_DATABASE and GPU_QUEUE_MONGO_TEST_DATABASE to a dedicated test database",
)
class MongoGpuQueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await gpu_queue._state.drop()
        await gpu_queue._ensure_state()

    async def asyncTearDown(self):
        await gpu_queue._state.drop()

    async def test_queue_fairness_exclusivity_and_stale_cleanup(self):
        with patch.object(gpu_queue, "_MAX_WAITING_PER_USER", 2):
            first = await gpu_queue.enqueue("alice", "comfyui:first")
            second = await gpu_queue.enqueue("alice", "comfyui:second")
            third = await gpu_queue.enqueue("bob", "furniture:segment")

        snapshot = await gpu_queue.queue_snapshot()
        self.assertEqual(
            [item["ticket_id"] for item in snapshot["queue"]],
            [first, third, second],
        )

        await gpu_queue.acquire(first, "claim-a")
        second_claim = asyncio.create_task(
            gpu_queue.acquire(third, "claim-b", timeout_seconds=3)
        )
        await asyncio.sleep(0.05)
        state = await gpu_queue._state.find_one({"_id": gpu_queue._STATE_ID})
        self.assertEqual(state["active"]["ticket_id"], first)
        await gpu_queue.release(first, "claim-a")
        await asyncio.wait_for(second_claim, timeout=2)
        state = await gpu_queue._state.find_one({"_id": gpu_queue._STATE_ID})
        self.assertEqual(state["active"]["ticket_id"], third)
        await gpu_queue.release(third, "claim-b")
        await gpu_queue.cancel(second, "test_cleanup")

        stale_active = await gpu_queue.enqueue("carol", "comfyui:stale")
        await gpu_queue.acquire(stale_active, "claim-stale")
        with self.assertRaises(gpu_queue.QueueTicketError):
            await gpu_queue.recover_stale_active(stale_active, "should reject a fresh lease")
        stale_at = gpu_queue._now() - timedelta(seconds=120)
        await gpu_queue._state.update_one(
            {"_id": gpu_queue._STATE_ID, "active.ticket_id": stale_active},
            {"$set": {"active.heartbeat_at": stale_at}},
        )
        await gpu_queue.recover_stale_active(stale_active, "operator confirmed the GPU is idle")
        self.assertEqual((await gpu_queue.status(stale_active))["status"], "failed")

        abandoned = await gpu_queue.enqueue("carol", "comfyui:abandoned")
        stale_at = gpu_queue._now() - timedelta(seconds=120)
        await gpu_queue._state.update_one(
            {"_id": gpu_queue._STATE_ID, "queue.ticket_id": abandoned},
            {"$set": {"queue.$.heartbeat_at": stale_at}},
        )
        live = await gpu_queue.enqueue("dave", "furniture:segment")
        self.assertIsNone(await gpu_queue.status(abandoned))
        self.assertEqual((await gpu_queue.status(live))["status"], "queued")


if __name__ == "__main__":
    unittest.main()