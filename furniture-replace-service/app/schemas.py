"""
API contract. Every request/response shape lives here so the endpoints in
app/api/*.py stay thin, and so this file alone documents the wire format for
whoever wires up the AInterior frontend later.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Shared / image input ─────────────────────────────────────────────────────

class ImageRef(BaseModel):
    """
    One of three ways to point this service at an image. Exactly one should be set.
    Keeping all three means AInterior's backend never has to change how it stores
    files just to talk to this service.

    image_url may be an external URL OR a local static path this service itself
    serves (e.g. "/results/masks/<id>.png", "/catalog-images/<id>.png"); local
    paths are read straight from disk, no HTTP round-trip.
    """
    image_base64: str | None = None
    image_url: str | None = None


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: float
    updated_at: float
    result: dict[str, Any] | None = None
    error: str | None = None


# ── /v1/segment ───────────────────────────────────────────────────────────────
# Segmentation is click-driven: the user clicks the object to replace and SAM 2.1
# returns its mask. No text prompts. (SAM 3 / auto segmentation is reserved for the
# offline furniture-library builder, not this interactive path — see scripts/.)

class Point(BaseModel):
    x: int
    y: int
    label: int = Field(1, description="1 = include (foreground), 0 = exclude (background)")


class SegmentRequest(BaseModel):
    image: ImageRef
    points: list[Point] = Field(
        ..., min_length=1,
        description="User clicks. At least one foreground point; extra points refine the mask.",
    )


class SegmentResult(BaseModel):
    mask_url: str  # PNG mask served as a static file under /results/masks/
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    score: float                     # SAM 2.1 predicted IoU for the returned mask
    image_width: int
    image_height: int


# ── /v1/match ─────────────────────────────────────────────────────────────────

class MatchRequest(BaseModel):
    image: ImageRef
    mask: ImageRef  # binary mask isolating the object to match
    top_k: int = 5
    category_filter: str | None = None


class ProductMatch(BaseModel):
    product_id: str
    name: str
    category: str
    price: float | None = None
    currency: str = "PLN"
    image_url: str
    similarity: float  # cosine similarity, 0..1


class MatchResult(BaseModel):
    matches: list[ProductMatch]


# ── /v1/replace ───────────────────────────────────────────────────────────────

class ReplaceMode(str, Enum):
    prompt = "prompt"        # text-guided — LaMa -> BrushNet
    reference = "reference"  # image-guided — IP-Adapter, exact product fidelity


class ReplaceRequest(BaseModel):
    image: ImageRef
    mask: ImageRef
    mode: ReplaceMode

    # mode == prompt
    prompt: str | None = None
    negative_prompt: str | None = None

    # mode == reference
    product_id: str | None = Field(
        default=None, description="Catalog product to use as IP-Adapter reference"
    )
    ip_scale: float | None = None  # overrides config default if set

    steps: int | None = None
    guidance_scale: float | None = None


class ReplaceResult(BaseModel):
    result_url: str
    stage1_url: str | None = None  # LaMa-cleaned background, useful for debugging
    mode: ReplaceMode
    elapsed_seconds: float


# ── /v1/catalog/products ──────────────────────────────────────────────────────

class ProductIngestRequest(BaseModel):
    image: ImageRef
    name: str
    category: str
    price: float | None = None
    currency: str = "PLN"
    product_id: str | None = Field(
        default=None, description="Provide to upsert; omitted -> generated"
    )


class ProductIngestResponse(BaseModel):
    product_id: str
    indexed: bool
    image_url: str


class CatalogListResponse(BaseModel):
    products: list[ProductMatch]
    count: int


# ── /v1/health ──────────────────────────────────────────────────────────────

class ModelStatus(BaseModel):
    name: str
    resident_on: str  # "gpu" | "cpu" | "not_loaded"
    last_used_seconds_ago: float | None = None


class HealthResponse(BaseModel):
    status: str
    device: str
    vram_allocated_mb: float | None = None
    vram_reserved_mb: float | None = None
    models: list[ModelStatus]
    queue_depth: int
