"""
API contract. Every request/response shape lives here so the endpoints in
app/api/*.py stay thin, and so this file alone documents the wire format for
whoever wires up the AInterior frontend later.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ImageRef(BaseModel):
    """
    One of three ways to point this service at an image. Exactly one should be set.
    Keeping all three means AInterior's backend never has to change how it stores
    files just to talk to this service.
    """
    image_base64: str | None = None
    image_url: str | None = None
    # multipart upload is handled separately via FastAPI's UploadFile in the route,
    # not through this model — see app/api/segment.py


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


class SegmentMode(str, Enum):
    text = "text"      # SAM 3 — automatic, no user interaction
    point = "point"    # SAM 2.1 — user clicked a point
    auto = "auto"      # SAM 2.1 — segment everything, filter by area heuristic


class SegmentRequest(BaseModel):
    image: ImageRef
    mode: SegmentMode = SegmentMode.text
    concepts: list[str] | None = Field(
        default=None,
        description="Text concepts for mode=text, e.g. ['sofa','armchair','floor lamp']",
    )
    point_xy: tuple[int, int] | None = Field(
        default=None, description="Click coordinates for mode=point"
    )
    confidence_threshold: float = 0.65


class Detection(BaseModel):
    concept: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    mask_url: str  # PNG mask served as a static file


class SegmentResult(BaseModel):
    detections: list[Detection]
    image_width: int
    image_height: int


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


class ReplaceMode(str, Enum):
    prompt = "prompt"
    reference = "reference"


class ReplaceRequest(BaseModel):
    image: ImageRef
    mask: ImageRef
    mode: ReplaceMode

    prompt: str | None = None
    negative_prompt: str | None = None

    product_id: str | None = Field(
        default=None, description="Catalog product to use as IP-Adapter reference"
    )
    ip_scale: float | None = None  # overrides config default (0.85) if set

    steps: int | None = None
    guidance_scale: float | None = None


class ReplaceResult(BaseModel):
    result_url: str
    stage1_url: str | None = None  # LaMa-cleaned background, useful for debugging
    mode: ReplaceMode
    elapsed_seconds: float


class ProductIngestResponse(BaseModel):
    product_id: str
    indexed: bool


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
