from typing import Literal

from pydantic import BaseModel, Field

class PanoramaRequest(BaseModel):
    model_id: str = Field(max_length=80)
    brief: str = Field(min_length=1, max_length=1500, pattern=r"\S")
    negative_prompt: str = Field(default="", max_length=500)
    seed: int = Field(ge=0, le=4294967295)
    quality: Literal["draft", "high"] = "draft"


class TextToImageRequest(BaseModel):
    model_version: str
    prompt: str = Field(max_length=2000)
    negative_prompt: str = Field(max_length=2000)
    guidance_scale: float
    width: int = Field(ge=64, le=1024, multiple_of=64)
    height: int = Field(ge=64, le=1024, multiple_of=64)
    seed: int


class Img2ImgRequest(BaseModel):
    model_version: str
    prompt: str
    negative_prompt: str
    guidance_scale: float
    seed: int
    image: str
    scaling_mode: str


class ControlNetRequest(BaseModel):
    model_version: str
    prompt: str
    negative_prompt: str
    guidance_scale: float
    cannyLowThreshold: float
    cannyHighThreshold: float
    seed: int
    image: str
    scaling_mode: str


class Inpainting(BaseModel):
    model_version: str
    prompt: str
    negative_prompt: str
    guidance_scale: float
    seed: int
    image: str
    mask_image: str
    

class Outpainting(BaseModel):
    model_version: str
    prompt: str
    negative_prompt: str
    guidance_scale: float
    seed: int
    pad_right: int
    pad_left: int
    pad_top: int
    pad_bottom: int
    image: str
    scaling_mode: str