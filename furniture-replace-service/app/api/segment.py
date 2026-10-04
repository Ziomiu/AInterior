"""POST /v1/segment — click-driven SAM 2.1. Async (returns a job)."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.jobs.queue import job_queue
from app.models.manager import model_manager
from app.models.segmentation import Segmenter
from app.schemas import SegmentRequest
from app.utils.images import load_rgb, mask_to_bbox, save_png
from PIL import Image

router = APIRouter(prefix="/v1", tags=["segment"])


@router.post("/segment")
async def segment(req: SegmentRequest):
    image = await asyncio.to_thread(load_rgb, req.image)
    points = [(p.x, p.y) for p in req.points]
    labels = [p.label for p in req.points]
    if not any(labels) or any(x >= image.width or y >= image.height for x, y in points):
        raise HTTPException(400, "Clicks must be inside the image and include a foreground point")

    def task() -> dict:
        with model_manager.use("segmenter") as seg:
            assert isinstance(seg, Segmenter)
            mask_arr, score = seg.segment_points(image, points, labels)

        mask_img = Image.fromarray((mask_arr * 255).astype("uint8"), mode="L")
        bbox = mask_to_bbox(mask_img) or (0, 0, image.width, image.height)

        mask_id = uuid.uuid4().hex
        save_png(mask_img, settings.masks_dir / f"{mask_id}.png")

        return {
            "mask_url": f"/results/masks/{mask_id}.png",
            "bbox": list(bbox),
            "score": round(score, 4),
            "image_width": image.width,
            "image_height": image.height,
        }

    job = job_queue.submit(task)
    return {"job_id": job.id, "status": job.status}
