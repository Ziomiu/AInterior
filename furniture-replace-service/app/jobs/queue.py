"""
Single-worker async job queue.

Heavy operations (segment, replace) take seconds. Rather than block the HTTP
request for that long, they enqueue a job and return a job_id immediately; the
client polls GET /v1/jobs/{id}.

One worker, on purpose. There is one GPU and the ModelManager keeps exactly one
heavy model resident at a time, so processing jobs sequentially is the correct
match to the hardware — concurrency here would only thrash VRAM. The blocking
inference call runs in a single-thread executor so the event loop stays free to
serve /jobs polling and /health while a job runs.
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from typing import Any, Callable

from fastapi import HTTPException

from app.config import settings
from app.schemas import JobStatus

logger = logging.getLogger("job_queue")


class Job:
    def __init__(self, job_id: str, fn: Callable[[], dict[str, Any]]):
        self.id = job_id
        self.fn: Callable[[], dict[str, Any]] | None = fn
        self.status: JobStatus = JobStatus.queued
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.created_at = time.time()
        self.updated_at = self.created_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
        }


class JobQueue:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue[Job] | None = None
        self._worker: asyncio.Task | None = None
        # A single worker thread => inference is serialized across the whole service.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="infer")

    def start(self) -> None:
        self._queue = asyncio.Queue(maxsize=settings.max_queued_jobs)
        self._worker = asyncio.create_task(self._run())
        logger.info("Job queue worker started")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker
        self._executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, fn: Callable[[], dict[str, Any]]) -> Job:
        assert self._queue is not None, "Queue not started"
        if self._queue.full():
            raise HTTPException(503, "Inference queue is full; retry later")
        job = Job(str(uuid.uuid4()), fn)
        self._jobs[job.id] = job
        self._queue.put_nowait(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def depth(self) -> int:
        return self._queue.qsize() if self._queue else 0

    def _trim_history(self) -> None:
        for job_id in list(self._jobs):
            if len(self._jobs) <= settings.max_job_history:
                break
            if self._jobs[job_id].status in (JobStatus.done, JobStatus.failed):
                del self._jobs[job_id]

    async def _run(self) -> None:
        assert self._queue is not None
        loop = asyncio.get_running_loop()
        while True:
            job = await self._queue.get()
            job.status = JobStatus.running
            job.updated_at = time.time()
            logger.info(f"[{job.id}] running")
            try:
                job.result = await loop.run_in_executor(self._executor, job.fn)
                job.status = JobStatus.done
                logger.info(f"[{job.id}] done")
            except Exception as exc:  # noqa: BLE001 — surface any failure to the client
                job.status = JobStatus.failed
                job.error = str(exc)
                logger.error(f"[{job.id}] failed: {exc}\n{traceback.format_exc()}")
            finally:
                job.fn = None
                job.updated_at = time.time()
                self._queue.task_done()
                self._trim_history()


job_queue = JobQueue()
