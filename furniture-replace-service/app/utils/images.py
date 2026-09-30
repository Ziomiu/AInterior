"""
Image plumbing: turn an ImageRef (base64 / url / local static path) into a PIL
image, and the small mask/crop helpers the pipeline needs. Isolated here so no
model or route code has to think about how bytes arrived.
"""
from __future__ import annotations

import base64
import binascii
import io
from pathlib import Path

import numpy as np
import requests
from fastapi import HTTPException
from PIL import Image, ImageOps

from app.config import settings
from app.schemas import ImageRef

# Map the two static mount points to their on-disk directories so a local
# static URL is read from disk instead of round-tripping through HTTP.
_LOCAL_PREFIXES: dict[str, Path] = {
    "/results/": settings.results_dir,
    "/catalog-images/": settings.catalog_images_dir,
}


def _decode_base64(data: str) -> Image.Image:
    if "," in data and data.strip().startswith("data:"):
        data = data.split(",", 1)[1]  # tolerate a full data URL
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, f"Invalid base64 image: {exc}") from exc
    return Image.open(io.BytesIO(raw))


def _load_url(url: str) -> Image.Image:
    for prefix, root in _LOCAL_PREFIXES.items():
        if url.startswith(prefix):
            local = root / url[len(prefix):]
            if not local.is_file():
                raise HTTPException(404, f"Local image not found: {url}")
            return Image.open(local)

    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, f"Unsupported image_url scheme: {url}")
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(400, f"Could not fetch image_url: {exc}") from exc
    return Image.open(io.BytesIO(resp.content))


def _resolve(ref: ImageRef) -> Image.Image:
    if ref.image_base64:
        return _decode_base64(ref.image_base64)
    if ref.image_url:
        return _load_url(ref.image_url)
    raise HTTPException(400, "ImageRef must set image_base64 or image_url")


def load_rgb(ref: ImageRef) -> Image.Image:
    """Load an ImageRef as an EXIF-corrected RGB image."""
    img = ImageOps.exif_transpose(_resolve(ref))
    return img.convert("RGB")


def load_mask(ref: ImageRef, size: tuple[int, int] | None = None) -> Image.Image:
    """
    Load an ImageRef as a single-channel binary mask (0/255). Optionally resize
    (nearest) to match a target (width, height) so mask and image always align.
    """
    mask = _resolve(ref).convert("L")
    if size is not None and mask.size != size:
        mask = mask.resize(size, Image.NEAREST)
    arr = (np.array(mask) > 127).astype(np.uint8) * 255
    return Image.fromarray(arr, mode="L")


def pil_to_base64(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")


def mask_to_bbox(mask: Image.Image) -> tuple[int, int, int, int] | None:
    """Tight bounding box (x1, y1, x2, y2) of the non-zero mask region."""
    arr = np.array(mask.convert("L")) > 127
    if not arr.any():
        return None
    ys, xs = np.where(arr)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def bbox_to_mask(bbox: tuple[int, int, int, int], size: tuple[int, int]) -> np.ndarray:
    x1, y1, x2, y2 = bbox
    m = np.zeros((size[1], size[0]), dtype=np.uint8)
    m[y1:y2, x1:x2] = 255
    return m


def crop_object_on_white(image: Image.Image, mask: Image.Image, pad: float = 0.08) -> Image.Image:
    """
    Isolate the masked object on a white background and crop to its bbox (with a
    little padding). This is what CLIP sees for matching — background removed so
    the embedding describes the *object*, not the room.
    """
    bbox = mask_to_bbox(mask)
    if bbox is None:
        return image
    x1, y1, x2, y2 = bbox
    w, h = image.size
    px, py = int((x2 - x1) * pad), int((y2 - y1) * pad)
    x1, y1 = max(0, x1 - px), max(0, y1 - py)
    x2, y2 = min(w, x2 + px), min(h, y2 + py)

    m = np.array(mask.convert("L"))[y1:y2, x1:x2] > 127
    obj = np.array(image.convert("RGB"))[y1:y2, x1:x2]
    white = np.full_like(obj, 255)
    out = np.where(m[..., None], obj, white)
    return Image.fromarray(out, mode="RGB")


def dilate_mask(mask: Image.Image, iterations: int = 6) -> Image.Image:
    """
    Grow the mask a few pixels. Inpainting a slightly enlarged region hides the
    seam where the old object met the wall/floor and avoids leaving a halo.
    """
    import cv2

    arr = np.array(mask.convert("L"))
    kernel = np.ones((3, 3), np.uint8)
    grown = cv2.dilate(arr, kernel, iterations=iterations)
    return Image.fromarray(grown, mode="L")
