"""
Segmentation — SAM 2.1, click-driven only.

The user clicks the object they want to replace; SAM 2.1 turns those clicks into
a pixel-perfect mask. There is no text-prompt / automatic detection in this
interactive path by design (see README). Automatic segmentation for building the
furniture library lives offline in scripts/build_library.py.

Registered with the ModelManager as a single heavy model named "segmenter".
"""
from __future__ import annotations

import logging

import numpy as np
import torch
from PIL import Image

from app.config import settings
from app.models.manager import model_manager

logger = logging.getLogger("segmentation")


def _best_mask_index(masks, scores, points, labels) -> int:
    def rank(index):
        agreement = sum(
            bool(masks[index, point_y, point_x] > 0) == bool(label)
            for (point_x, point_y), label in zip(points, labels)
        )
        return agreement, float(scores[index])

    return max(range(len(scores)), key=rank)


class Segmenter:
    """Thin wrapper around SAM2ImagePredictor with CPU<->GPU movement."""

    def __init__(self, predictor) -> None:
        self.predictor = predictor
        self.device = "cpu"

    def to(self, device: str) -> "Segmenter":
        # SAM2ImagePredictor keeps the network on predictor.model.
        self.predictor.model.to(device)
        if device == "cpu":
            self.predictor.reset_predictor()
        self.device = device
        return self

    @torch.inference_mode()
    def segment_points(
        self,
        image: Image.Image,
        points: list[tuple[int, int]],
        labels: list[int],
    ) -> tuple[np.ndarray, float]:
        """
        Returns (binary_mask HxW uint8 {0,1}, predicted_iou) for the highest-scoring
        mask SAM proposes for the given clicks.
        """
        self.predictor.set_image(np.array(image))
        point_coords = np.array(points, dtype=np.float32)
        point_labels = np.array(labels, dtype=np.int32)

        masks, scores, _ = self.predictor.predict(
            point_coords=point_coords,
            point_labels=point_labels,
            multimask_output=True,  # let SAM propose 3, we keep the best
        )
        best = _best_mask_index(masks, scores, points, labels)
        mask = (masks[best] > 0).astype(np.uint8)
        return mask, float(scores[best])


def _load_segmenter() -> Segmenter:
    """Build SAM 2.1 on CPU. Weights download from the Hub on first run."""
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    predictor = SAM2ImagePredictor.from_pretrained(settings.sam2_model, device="cpu")
    return Segmenter(predictor)


def register_segmentation_models() -> None:
    model_manager.register(
        "segmenter",
        loader=_load_segmenter,
        to_device_fn=lambda seg, dev: seg.to(dev),
    )
