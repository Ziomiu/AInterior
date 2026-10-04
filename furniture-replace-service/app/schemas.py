"""
API contract. Every request/response shape lives here so the endpoints in
app/api/*.py stay thin, and so this file alone documents the wire format for
whoever wires up the AInterior frontend later.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


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

    @model_validator(mode="after")
    def validate_source(self):
        if bool(self.image_base64) == bool(self.image_url):
            raise ValueError("Set exactly one of image_base64 or image_url")
        return self


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


# Segmentation is click-driven: the user clicks the object to replace and SAM 2.1
# returns its mask. No text prompts. (SAM 3 / auto segmentation is reserved for the
# offline furniture-library builder, not this interactive path — see scripts/.)

class Point(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    label: Literal[0, 1] = Field(1, description="1 = include (foreground), 0 = exclude (background)")


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


class MatchRequest(BaseModel):
    image: ImageRef
    mask: ImageRef  # binary mask isolating the object to match
    top_k: int = Field(5, ge=1, le=50)
    category_filter: str | None = None
    product_ids: list[str] | None = None


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

    product_id: UUID | None = Field(
        default=None, description="Catalog product to use as IP-Adapter reference"
    )
    ip_scale: float | None = Field(None, ge=0, le=1.5)

    steps: int | None = Field(None, ge=1, le=80)
    guidance_scale: float | None = Field(None, ge=0, le=20)
    seed: int = Field(0, ge=0, le=2**32 - 1)
    quality: Literal["balanced", "quality"] = "balanced"
    mask_growth: int = Field(6, ge=0, le=32)
    edge_blend: int = Field(2, ge=0, le=8)


class ReplaceResult(BaseModel):
    result_url: str
    stage1_url: str | None = None  # LaMa-cleaned background, useful for debugging
    mode: ReplaceMode
    elapsed_seconds: float


class ProductIngestRequest(BaseModel):
    image: ImageRef
    name: str
    category: str
    price: float | None = None
    currency: str = "PLN"
    product_id: UUID | None = Field(
        default=None, description="Provide to upsert; omitted -> generated"
    )


class ProductIngestResponse(BaseModel):
    product_id: str
    indexed: bool
    image_url: str


class CatalogListResponse(BaseModel):
    products: list[ProductMatch]
    count: int


class ModelStatus(BaseModel):
    name: str
    resident_on: str  # "gpu" | "cpu" | "not_loaded"
    backend: str | None = None
    last_used_seconds_ago: float | None = None


class HealthResponse(BaseModel):
    status: str
    device: str
    vram_allocated_mb: float | None = None
    vram_reserved_mb: float | None = None
    models: list[ModelStatus]
    queue_depth: int
    inference_config: dict[str, Any] = Field(default_factory=dict)
