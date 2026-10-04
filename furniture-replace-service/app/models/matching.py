"""
Matching model — CLIP image embeddings.

CLIP is the only "light" model here: <1GB, used on almost every request (both to
embed a masked object for search, and to embed catalog products at ingest time),
so the ModelManager keeps it GPU-resident permanently.
"""
from __future__ import annotations

import logging

import numpy as np
import torch
from PIL import Image

from app.config import settings
from app.models.manager import model_manager

logger = logging.getLogger("matching")


class ClipEmbedder:
    def __init__(self, model, processor) -> None:
        self.model = model
        self.processor = processor
        self.device = "cpu"

    def to(self, device: str) -> "ClipEmbedder":
        self.model.to(device)
        self.device = device
        return self

    @torch.inference_mode()
    def embed_image(self, image: Image.Image) -> np.ndarray:
        """Return an L2-normalized CLIP image embedding (float32, clip_embed_dim)."""
        inputs = self.processor(images=image, return_tensors="pt").to(self.device)
        feats = self.model.get_image_features(**inputs)
        feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
        return feats[0].cpu().numpy().astype(np.float32)


def _load_clip() -> ClipEmbedder:
    from transformers import CLIPModel, CLIPProcessor

    model = CLIPModel.from_pretrained(settings.clip_model)
    processor = CLIPProcessor.from_pretrained(settings.clip_model)
    model.eval()
    return ClipEmbedder(model, processor)


def register_matching_model() -> None:
    model_manager.register(
        "clip",
        loader=_load_clip,
        to_device_fn=lambda emb, dev: emb.to(dev),
    )
