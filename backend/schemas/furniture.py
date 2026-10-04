from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class FurniturePoint(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    label: Literal[0, 1] = 1


class FurnitureSegmentRequest(BaseModel):
    image: str = Field(min_length=1, max_length=7_000_000)
    points: list[FurniturePoint] = Field(min_length=1, max_length=64)


class FurnitureMaskRequest(BaseModel):
    image: str = Field(min_length=1, max_length=7_000_000)
    mask_job_id: UUID
    mask: str | None = Field(None, min_length=1, max_length=7_000_000)


class FurnitureMatchRequest(FurnitureMaskRequest):
    top_k: int = Field(6, ge=1, le=20)
    category_filter: str | None = Field(None, max_length=100)


class FurnitureReplaceRequest(FurnitureMaskRequest):
    mode: Literal["prompt", "reference"] = "prompt"
    prompt: str | None = Field(None, max_length=2000)
    negative_prompt: str | None = Field(None, max_length=2000)
    product_id: UUID | None = None
    quality: Literal["balanced", "quality"] = "balanced"
    seed: int = Field(0, ge=0, le=2**32 - 1)
    steps: int = Field(30, ge=1, le=80)
    guidance_scale: float = Field(7.5, ge=0, le=20)
    ip_scale: float = Field(0.85, ge=0, le=1.5)
    mask_growth: int = Field(6, ge=0, le=32)
    edge_blend: int = Field(2, ge=0, le=8)

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == "prompt" and not (self.prompt or "").strip():
            raise ValueError("Prompt is required")
        if self.mode == "reference" and self.product_id is None:
            raise ValueError("Select a reference product")
        if self.mode == "reference" and self.quality == "quality":
            raise ValueError("Quality profile is only available for prompt mode")
        return self


class FurnitureProductRequest(BaseModel):
    image: str = Field(min_length=1, max_length=7_000_000)
    name: str = Field(min_length=1, max_length=150)
    category: str = Field(min_length=1, max_length=100)