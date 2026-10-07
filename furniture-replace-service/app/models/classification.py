from __future__ import annotations

import math
from collections.abc import Sequence


FURNITURE_CATEGORIES = (
    "chair", "sofa", "table", "bed", "cabinet", "shelf", "desk", "stool", "bench", "lamp",
)
CLASSIFICATION_LABELS = FURNITURE_CATEGORIES + (
    "other object", "wall", "floor", "ceiling", "window", "door", "room background",
    "person", "plant", "appliance",
)
MIN_COSINE_SIMILARITY = 0.25
MIN_CATEGORY_MARGIN = 0.04
RELATIVE_SCORE_TEMPERATURE = 0.07


def unknown_classification(confidence: float = 0.0) -> dict:
    return {
        "category": "unknown",
        "label": "other object",
        "confidence": round(confidence, 4),
        "uncertain": True,
        "confidence_kind": "relative_clip_score",
    }


def rank_categories(similarities: Sequence[float]) -> dict:
    scores = tuple(float(score) for score in similarities)
    if len(scores) != len(CLASSIFICATION_LABELS) or not all(math.isfinite(score) for score in scores):
        return unknown_classification()
    ranked = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
    winner, runner_up = ranked[:2]
    peak = scores[winner]
    confidence = 1.0 / sum(
        math.exp((score - peak) / RELATIVE_SCORE_TEMPERATURE) for score in scores
    )
    category = CLASSIFICATION_LABELS[winner]
    if (category not in FURNITURE_CATEGORIES or peak < MIN_COSINE_SIMILARITY
            or peak - scores[runner_up] < MIN_CATEGORY_MARGIN):
        return unknown_classification(confidence)
    return {
        "category": category,
        "label": category,
        "confidence": round(confidence, 4),
        "uncertain": False,
        "confidence_kind": "relative_clip_score",
    }