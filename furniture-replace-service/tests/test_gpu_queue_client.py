import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

from app import gpu_queue


class ActiveHeartbeatTests(unittest.TestCase):
    def test_heartbeat_retries_after_a_transient_request_error(self):
        stop = threading.Event()
        calls = []

        def request(action, ticket_id, claim_id):
            calls.append((action, ticket_id, claim_id))
            if len(calls) == 1:
                raise requests.ConnectionError("temporary failure")
            stop.set()

        with patch.object(gpu_queue, "settings", SimpleNamespace(gpu_queue_heartbeat_seconds=0.001)), \
             patch.object(gpu_queue, "_request", side_effect=request):
            worker = threading.Thread(
                target=gpu_queue._heartbeat_loop,
                args=("ticket", "claim", stop),
            )
            worker.start()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(calls, [("heartbeat", "ticket", "claim")] * 2)


if __name__ == "__main__":
    unittest.main()