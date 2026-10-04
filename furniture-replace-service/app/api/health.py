"""GET /v1/health — model residency, VRAM, queue depth."""
from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
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
        inference_config={
            "sam2_model": settings.sam2_model,
            "sd_inpaint_model": settings.sd_inpaint_model,
            "prompt_inpaint_model": settings.prompt_inpaint_model or settings.sd_inpaint_model,
            "sd_inpaint_variant": settings.sd_inpaint_variant,
            "ip_adapter_weight": settings.ip_adapter_weight,
            "prompt_clean_first": settings.prompt_clean_first,
            "inpaint_crop_padding": settings.inpaint_crop_padding,
        },
    )
