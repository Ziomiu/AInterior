import asyncio
from enum import Enum
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


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
        "app.config": SimpleNamespace(settings=SimpleNamespace(max_queued_jobs=2, max_job_history=2)),
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


if __name__ == "__main__":
    unittest.main()