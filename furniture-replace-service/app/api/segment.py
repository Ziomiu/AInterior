"""POST /v1/segment — click-driven SAM 2.1. Async (returns a job)."""
from __future__ import annotations

import asyncio
import logging
import math
import uuid

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.gpu_queue import ticket_id_from_request
from app.jobs.queue import job_queue, report_stage
from app.models.classification import unknown_classification
from app.models.manager import model_manager
from app.models.matching import ClipEmbedder
from app.models.segmentation import Segmenter
from app.schemas import SegmentRequest
from app.utils.images import crop_object_on_white, load_rgb, mask_to_bbox, save_png
from PIL import Image

router = APIRouter(prefix="/v1", tags=["segment"])
logger = logging.getLogger("segment")


def _mask_review_required(mask, score, points, labels) -> bool:
    coverage = float((mask > 0).mean())
    return (
        not math.isfinite(score) or score < 0.85 or coverage <= 0.001 or coverage >= 0.85
        or any(bool(mask[y, x]) != bool(label) for (x, y), label in zip(points, labels))
    )


@router.post("/segment")
async def segment(req: SegmentRequest, request: Request):
    gpu_ticket_id = ticket_id_from_request(request)
    image = await asyncio.to_thread(load_rgb, req.image)
    points = [(p.x, p.y) for p in req.points]
    labels = [p.label for p in req.points]
    if not any(labels) or any(x >= image.width or y >= image.height for x, y in points):
        raise HTTPException(400, "Clicks must be inside the image and include a foreground point")

    def task() -> dict:
        report_stage("loading")
        with model_manager.use("segmenter") as seg:
            assert isinstance(seg, Segmenter)
            report_stage("segmenting")
            mask_arr, score = seg.segment_points(image, points, labels)

        mask_img = Image.fromarray((mask_arr * 255).astype("uint8"), mode="L")
        bbox = mask_to_bbox(mask_img)
        mask_review_required = _mask_review_required(mask_arr, score, points, labels)
        classification = unknown_classification()
        if bbox is not None:
            try:
                report_stage("loading")
                with model_manager.use("clip") as clip:
                    assert isinstance(clip, ClipEmbedder)
                    report_stage("classifying")
                    classification = clip.classify_object(crop_object_on_white(image, mask_img))
            except Exception:
                logger.exception("Object classification failed; retaining the SAM mask")
        bbox = bbox or (0, 0, image.width, image.height)

        mask_id = uuid.uuid4().hex
        report_stage("saving")
        save_png(mask_img, settings.masks_dir / f"{mask_id}.png")

        return {
            "mask_url": f"/results/masks/{mask_id}.png",
            "bbox": list(bbox),
            "score": round(score, 4),
            "classification": classification,
            "mask_review_required": mask_review_required,
            "image_width": image.width,
            "image_height": image.height,
        }

    job = job_queue.submit(task, gpu_ticket_id)
    return {"job_id": job.id, "status": job.status}
