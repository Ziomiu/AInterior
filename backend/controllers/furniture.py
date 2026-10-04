import asyncio
import base64
import binascii
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import os
import re
from uuid import UUID, uuid4

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
import httpx
from PIL import Image, ImageOps

from database.mongo import db
from schemas.furniture import (
    FurnitureMatchRequest, FurnitureProductRequest, FurnitureReplaceRequest,
    FurnitureSegmentRequest,
)
from utils.auth_helpers import get_current_user

furniture_router = APIRouter()
jobs_collection = db["furniture_jobs"]
images_collection = db["generated_images"]
products_collection = db["furniture_products"]
_ASSET_PATH = re.compile(r"/(?:results/(?:masks/)?|catalog-images/)[a-f0-9-]{32,36}(?:_stage1)?\.png\Z")
_MAX_ASSET_BYTES = 8 * 1024 * 1024


async def _service(method: str, path: str, **kwargs):
    url = os.getenv("FURNITURE_SERVICE_URL", "http://furniture-replace:8000").rstrip("/")
    key = os.getenv("FURNITURE_SERVICE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5), follow_redirects=False) as client:
            response = await client.request(method, url + path, headers={"X-Service-Key": key}, **kwargs)
        if response.status_code in (400, 413, 422):
            raise HTTPException(response.status_code, response.json().get("detail", "Invalid replacement request"))
        if response.status_code >= 400:
            raise HTTPException(503, "Furniture service unavailable")
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Furniture service unavailable") from exc


async def _asset(path: str) -> str:
    if not _ASSET_PATH.fullmatch(path):
        raise HTTPException(502, "Invalid image path returned by furniture service")
    url = os.getenv("FURNITURE_SERVICE_URL", "http://furniture-replace:8000").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            async with client.stream("GET", url + path, headers={"X-Service-Key": os.getenv("FURNITURE_SERVICE_KEY", "")}) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > _MAX_ASSET_BYTES:
                        raise HTTPException(502, "Furniture image exceeds the size limit")
                    content.extend(chunk)
        return base64.b64encode(content).decode("ascii")
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Furniture image unavailable") from exc


def _validate_image(data: str) -> tuple[int, int]:
    try:
        content = base64.b64decode(data, validate=True)
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(413, "Image must be at most 5 MB")
        with Image.open(BytesIO(content)) as image:
            if max(image.size) > 4096 or image.width * image.height > 16_777_216:
                raise HTTPException(413, "Image dimensions exceed the limit")
            image = ImageOps.exif_transpose(image)
            image.load()
            return image.size
    except (binascii.Error, ValueError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(400, "Invalid image") from exc


async def _owned_job(job_id: UUID, current_user: dict):
    job = await jobs_collection.find_one({"_id": str(job_id), "user_id": current_user["_id"]})
    if job is None:
        raise HTTPException(404, "Furniture job not found")
    return job


async def _refresh(job: dict) -> dict:
    if job["status"] in ("done", "failed"):
        return job
    upstream = await _service("GET", f"/v1/jobs/{job['_id']}")
    status = upstream.get("status")
    if status not in ("queued", "running", "done", "failed"):
        raise HTTPException(502, "Invalid furniture job status")
    updates = {"status": status}
    if status == "done":
        result = dict(upstream.get("result") or {})
        field = "mask_url" if job["operation"] == "segment" else "result_url"
        if not isinstance(result.get(field), str) or not _ASSET_PATH.fullmatch(result[field]):
            raise HTTPException(502, "Invalid furniture job result")
        updates["service_result"] = result
    if status == "failed":
        updates["error"] = str(upstream.get("error", "Inference failed"))[:500]
    await jobs_collection.update_one({"_id": job["_id"], "user_id": job["user_id"]}, {"$set": updates})
    return {**job, **updates}


async def _mask(req, current_user):
    job = await _refresh(await _owned_job(req.mask_job_id, current_user))
    if job["operation"] != "segment" or job["status"] != "done":
        raise HTTPException(409, "Segmentation must finish first")
    dimensions = await asyncio.to_thread(_validate_image, req.image)
    if list(dimensions) != job["dimensions"]:
        raise HTTPException(400, "Image does not match the segmentation dimensions")
    if hashlib.sha256(req.image.encode("ascii")).hexdigest() != job["image_hash"]:
        raise HTTPException(400, "Segment this image before replacing furniture")
    if req.mask:
        if await asyncio.to_thread(_validate_image, req.mask) != dimensions:
            raise HTTPException(400, "Mask dimensions must match the image")
        return {"image_base64": req.mask}, dimensions
    return {"image_url": job["service_result"]["mask_url"]}, dimensions


async def _submit(operation: str, payload: dict, current_user: dict, dimensions, metadata=None):
    await jobs_collection.create_index("expires_at", expireAfterSeconds=0)
    upstream = await _service("POST", f"/v1/{operation}", json=payload)
    try:
        job_id = str(UUID(upstream["job_id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(502, "Invalid furniture job ID") from exc
    now = datetime.now(timezone.utc)
    await jobs_collection.insert_one({
        "_id": job_id, "user_id": current_user["_id"], "operation": operation,
        "status": "queued", "dimensions": list(dimensions), "metadata": metadata or {},
        "gallery_id": ObjectId(), "created_at": now, "expires_at": now + timedelta(days=2),
        "image_hash": hashlib.sha256(payload["image"]["image_base64"].encode("ascii")).hexdigest(),
    })
    return {"job_id": job_id, "status": "queued"}


@furniture_router.get("/health")
async def health(current_user: dict = Depends(get_current_user)):
    return await _service("GET", "/v1/health")


@furniture_router.post("/segment")
async def segment(req: FurnitureSegmentRequest, current_user: dict = Depends(get_current_user)):
    dimensions = await asyncio.to_thread(_validate_image, req.image)
    if not any(point.label for point in req.points) or any(point.x >= dimensions[0] or point.y >= dimensions[1] for point in req.points):
        raise HTTPException(400, "Include a foreground click inside the image")
    return await _submit("segment", {
        "image": {"image_base64": req.image}, "points": [point.model_dump() for point in req.points],
    }, current_user, dimensions)


@furniture_router.get("/jobs/{job_id}")
async def job_status(job_id: UUID, current_user: dict = Depends(get_current_user)):
    job = await _refresh(await _owned_job(job_id, current_user))
    result = None
    if job["status"] == "done":
        upstream = job["service_result"]
        if job["operation"] == "segment":
            result = {"mask": await _asset(upstream["mask_url"]), "bbox": upstream.get("bbox"), "score": upstream.get("score")}
        else:
            result = {"image": await _asset(upstream["result_url"]), "elapsed_seconds": upstream.get("elapsed_seconds"), **job["metadata"]}
    return {"job_id": job["_id"], "status": job["status"], "result": result, "error": job.get("error")}


async def _product_access(product_id, current_user):
    product = await products_collection.find_one({"_id": str(UUID(str(product_id)))})
    return product is not None and product.get("status", "ready") == "ready" and (
        product.get("shared") is True or product.get("user_id") == current_user["_id"]
    )


async def _products(rows, current_user, limit=20):
    visible = []
    for product in rows:
        if await _product_access(product["product_id"], current_user):
            visible.append({**{key: value for key, value in product.items() if key != "image_url"},
                            "image": await _asset(product["image_url"])})
            if len(visible) >= limit:
                break
    return visible


@furniture_router.get("/products")
async def products(current_user: dict = Depends(get_current_user)):
    data = await _service("GET", "/v1/catalog/products", params={"limit": 200})
    return {"products": await _products(data["products"], current_user)}


@furniture_router.post("/products")
async def ingest(req: FurnitureProductRequest, current_user: dict = Depends(get_current_user)):
    await asyncio.to_thread(_validate_image, req.image)
    product_id = str(uuid4())
    await products_collection.insert_one({"_id": product_id, "user_id": current_user["_id"], "status": "pending"})
    result = await _service("POST", "/v1/catalog/products", json={
        "image": {"image_base64": req.image}, "name": req.name, "category": req.category, "product_id": product_id,
    })
    try:
        returned_id = str(UUID(result["product_id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(502, "Invalid reference product ID returned by furniture service") from exc
    if returned_id != product_id:
        raise HTTPException(502, "Reference product ID does not match its owner record")
    await products_collection.update_one({"_id": product_id, "user_id": current_user["_id"]}, {"$set": {"status": "ready"}})
    return {"product_id": product_id, "name": req.name, "category": req.category, "image": req.image}


@furniture_router.post("/match")
async def match(req: FurnitureMatchRequest, current_user: dict = Depends(get_current_user)):
    mask, _ = await _mask(req, current_user)
    data = await _service("POST", "/v1/match", json={
        "image": {"image_base64": req.image}, "mask": mask,
        "top_k": 50, "category_filter": req.category_filter,
    })
    return {"matches": await _products(data["matches"], current_user, req.top_k)}


@furniture_router.post("/replace")
async def replace(req: FurnitureReplaceRequest, current_user: dict = Depends(get_current_user)):
    mask, dimensions = await _mask(req, current_user)
    if req.product_id is not None and not await _product_access(req.product_id, current_user):
        raise HTTPException(404, "Reference product not found")
    metadata = req.model_dump(mode="json", exclude={"image", "mask", "mask_job_id"})
    payload = {**metadata, "image": {"image_base64": req.image}, "mask": mask}
    return await _submit("replace", payload, current_user, dimensions, metadata)


@furniture_router.post("/jobs/{job_id}/save")
async def save(job_id: UUID, current_user: dict = Depends(get_current_user)):
    job = await _refresh(await _owned_job(job_id, current_user))
    if job["operation"] != "replace" or job["status"] != "done":
        raise HTTPException(409, "Replacement must finish before saving")
    existing = await images_collection.find_one({"_id": job["gallery_id"], "user_id": current_user["_id"]})
    if existing is None:
        image = await _asset(job["service_result"]["result_url"])
        metadata = job["metadata"]
        await images_collection.update_one({"_id": job["gallery_id"], "user_id": current_user["_id"]}, {"$setOnInsert": {
            "image_base64": image, "created_at": datetime.now(timezone.utc), **metadata,
            "mode": "furniture-replace", "replacement_mode": metadata["mode"],
            "model": "sdxl-inpainting" if metadata["quality"] == "quality" else "sd1.5-inpainting",
            "width": job["dimensions"][0], "height": job["dimensions"][1], "furniture_job_id": job["_id"],
        }}, upsert=True)
    return {"image_id": str(job["gallery_id"])}