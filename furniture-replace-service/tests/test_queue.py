import asyncio
from enum import Enum
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import nullcontext


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


def load_queue():
    source = Path(__file__).resolve().parents[1] / "app/jobs/queue.py"
    spec = importlib.util.spec_from_file_location("queue_under_test", source)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "fastapi": SimpleNamespace(HTTPException=HTTPException),
        "app.schemas": SimpleNamespace(JobStatus=JobStatus),
        "app.config": SimpleNamespace(settings=SimpleNamespace(
            max_queued_jobs=2, max_job_history=2, gpu_queue_heartbeat_seconds=1,
        )),
        "app.gpu_queue": SimpleNamespace(
            cancel_job_ticket=lambda ticket_id: asyncio.sleep(0),
            gpu_slot=lambda ticket_id: nullcontext(),
            heartbeat_waiting_job_ticket=lambda ticket_id: asyncio.sleep(0, result=False),
        ),
    }):
        spec.loader.exec_module(module)
    return module


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.queue = load_queue().JobQueue()
        self.queue.start()

    async def asyncTearDown(self):
        await self.queue.stop()

    async def test_queue_rejects_excess_pending_jobs(self):
        self.queue.submit(lambda: {})
        self.queue.submit(lambda: {})
        with self.assertRaises(HTTPException) as error:
            self.queue.submit(lambda: {})
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(self.queue.depth(), 2)
        await asyncio.wait_for(self.queue._queue.join(), timeout=2)

    async def test_completed_job_releases_input_closure(self):
        job = self.queue.submit(lambda: {"result": "ok"})
        await asyncio.wait_for(self.queue._queue.join(), timeout=2)
        self.assertEqual(job.status, JobStatus.done)
        self.assertEqual(job.result, {"result": "ok"})
        self.assertIsNone(job.fn)

    async def test_completed_history_is_bounded(self):
        jobs = []
        for _ in range(3):
            jobs.append(self.queue.submit(lambda: {}))
            await asyncio.wait_for(self.queue._queue.join(), timeout=2)
        self.assertIsNone(self.queue.get(jobs[0].id))
        self.assertIsNotNone(self.queue.get(jobs[-1].id))

    async def test_stage_is_reported_from_the_active_worker_only(self):
        module = load_queue()
        queue = module.JobQueue()
        queue.start()
        observed = []

        def task():
            module.report_stage("generating")
            observed.append(job.as_dict()["stage"])
            return {}

        try:
            job = queue.submit(task)
            self.assertEqual(job.as_dict()["stage"], "queued")
            await asyncio.wait_for(queue._queue.join(), timeout=2)
            self.assertEqual(observed, ["generating"])
            self.assertEqual(job.as_dict()["stage"], "done")
            module.report_stage("outside_worker")
            self.assertEqual(job.stage, "done")
        finally:
            await queue.stop()

    async def test_ticket_heartbeat_stops_after_shared_queue_claims_ticket(self):
        module = load_queue()
        calls = 0

        async def heartbeat(ticket_id):
            nonlocal calls
            calls += 1
            return calls < 3

        async def no_wait(_seconds):
            return None

        with patch.object(module, "heartbeat_waiting_job_ticket", heartbeat), \
             patch.object(module.asyncio, "sleep", no_wait):
            await module.JobQueue()._keep_ticket_alive("ticket")

        self.assertEqual(calls, 3)


if __name__ == "__main__":
    unittest.main()