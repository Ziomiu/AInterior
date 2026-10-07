"""POST /v1/replace — prompt (LaMa->BrushNet) or reference (IP-Adapter). Async."""
from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from app.catalog.store import catalog_store
from app.config import settings
from app.gpu_queue import ticket_id_from_request
from app.jobs.queue import job_queue, report_stage
from app.pipeline import run_prompt_replace, run_reference_replace
from app.schemas import ImageRef, ReplaceMode, ReplaceRequest
from app.utils.images import load_mask, load_rgb, mask_to_bbox, save_png

router = APIRouter(prefix="/v1", tags=["replace"])


@router.post("/replace")
async def replace(req: ReplaceRequest, request: Request):
    gpu_ticket_id = ticket_id_from_request(request)
    image = await asyncio.to_thread(load_rgb, req.image)
    mask = await asyncio.to_thread(load_mask, req.mask, size=image.size)
    if mask_to_bbox(mask) is None:
        raise HTTPException(400, "Mask must contain a selected region")
    if req.mode == ReplaceMode.reference and req.quality == "quality":
        raise HTTPException(400, "Quality profile is available for prompt mode only")

    steps = req.steps if req.steps is not None else settings.default_steps
    guidance = req.guidance_scale if req.guidance_scale is not None else settings.default_guidance_scale

    # Resolve everything that needs the request/HTTP layer up-front, so the job
    # closure only touches models + disk.
    if req.mode == ReplaceMode.prompt:
        if not req.prompt:
            raise HTTPException(400, "mode=prompt requires a 'prompt'")
        prompt, neg = req.prompt, req.negative_prompt
        product_image = None
        ip_scale = None
    else:
        if not req.product_id:
            raise HTTPException(400, "mode=reference requires a 'product_id'")
        product = await asyncio.to_thread(catalog_store.get, str(req.product_id))
        if not product:
            raise HTTPException(404, f"Unknown product_id: {req.product_id}")
        product_image = await asyncio.to_thread(load_rgb, ImageRef(image_url=product["image_url"]))
        ip_scale = req.ip_scale if req.ip_scale is not None else settings.default_ip_scale
        prompt = req.prompt or f"{product.get('name', 'furniture')}, {product.get('category', '')}, realistic furniture, matching the room perspective and lighting"
        neg = None

    def task() -> dict:
        t0 = time.time()
        result_id = uuid.uuid4().hex
        stage1_url = None

        if req.mode == ReplaceMode.prompt:
            final, stage1 = run_prompt_replace(image, mask, prompt, neg, steps, guidance,
                seed=req.seed, quality=req.quality, mask_growth=req.mask_growth, edge_blend=req.edge_blend)
            if stage1 is not None:
                report_stage("saving")
                save_png(stage1, settings.results_dir / f"{result_id}_stage1.png")
                stage1_url = f"/results/{result_id}_stage1.png"
        else:
            final = run_reference_replace(image, mask, product_image, ip_scale, steps, guidance,
                seed=req.seed, prompt=prompt, mask_growth=req.mask_growth, edge_blend=req.edge_blend)

        report_stage("saving")
        save_png(final, settings.results_dir / f"{result_id}.png")
        return {
            "result_url": f"/results/{result_id}.png",
            "stage1_url": stage1_url,
            "mode": req.mode.value,
            "elapsed_seconds": round(time.time() - t0, 2),
            "seed": req.seed,
            "quality": req.quality,
        }

    job = job_queue.submit(task, gpu_ticket_id)
    return {"job_id": job.id, "status": job.status}
