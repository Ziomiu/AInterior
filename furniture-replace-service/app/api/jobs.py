"""GET /v1/jobs/{id} — poll a queued/running/done/failed job."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.jobs.queue import job_queue
from app.schemas import JobResponse

router = APIRouter(prefix="/v1", tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    job = job_queue.get(job_id)
    if job is None:
        raise HTTPException(404, f"Unknown job_id: {job_id}")
    return JobResponse(**job.as_dict())
