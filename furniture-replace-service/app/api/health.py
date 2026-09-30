"""GET /v1/health — model residency, VRAM, queue depth."""
from __future__ import annotations

from fastapi import APIRouter

from app.jobs.queue import job_queue
from app.models.manager import model_manager
from app.schemas import HealthResponse, ModelStatus

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    vram = model_manager.vram_stats()
    return HealthResponse(
        status="ok",
        device=model_manager.device,
        vram_allocated_mb=vram["vram_allocated_mb"],
        vram_reserved_mb=vram["vram_reserved_mb"],
        models=[ModelStatus(**m) for m in model_manager.status()],
        queue_depth=job_queue.depth(),
    )
