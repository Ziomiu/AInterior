import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from controllers import gpu_queue as queue_controller


class GPUQueueAPIKeyTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(queue_controller.router)
        self.client = TestClient(self.app)
        self.env_patch = patch.dict(os.environ, {"FURNITURE_SERVICE_KEY": "queue-test-key"})
        self.env_patch.start()
        self.snapshot = patch.object(
            queue_controller, "queue_snapshot", AsyncMock(return_value={"active": None, "queue": []}),
        )
        self.recover = patch.object(queue_controller, "recover_stale_active", AsyncMock())
        self.snapshot_mock = self.snapshot.start()
        self.recover_mock = self.recover.start()

    def tearDown(self):
        self.client.close()
        self.snapshot.stop()
        self.recover.stop()
        self.env_patch.stop()

    def test_queue_status_requires_the_service_key(self):
        response = self.client.get("/internal/gpu-queue/status")

        self.assertEqual(response.status_code, 401)
        self.snapshot_mock.assert_not_awaited()

    def test_stalled_recovery_requires_explicit_idle_confirmation(self):
        response = self.client.post("/internal/gpu-queue/ticket/recover", json={
            "confirm_gpu_idle": False,
            "reason": "operator checked status",
        }, headers={"X-Service-Key": "queue-test-key"})

        self.assertEqual(response.status_code, 400)
        self.recover_mock.assert_not_awaited()

    def test_confirmed_recovery_calls_the_stale_lease_guard(self):
        response = self.client.post("/internal/gpu-queue/ticket/recover", json={
            "confirm_gpu_idle": True,
            "reason": "GPU checked idle by operator",
        }, headers={"X-Service-Key": "queue-test-key"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "recovered"})
        self.recover_mock.assert_awaited_once_with("ticket", "GPU checked idle by operator")