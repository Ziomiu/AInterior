"""
Replacement orchestration. Keeps the multi-model choreography (resize -> run ->
composite back at full res) out of the HTTP routes. Both entry points run inside
a job-queue worker thread, so they may block on GPU work freely.
"""
from __future__ import annotations

import logging

import numpy as np
import torch
from PIL import Image, ImageFilter

from app.config import settings
from app.models.manager import model_manager
from app.utils.images import dilate_mask

logger = logging.getLogger("pipeline")

# SD1.5 / BrushNet are trained around 512px; running much larger degrades quality
# and VRAM. We process at a bounded working size and composite back at full res.
_MAX_SIDE = 768


def _work_size(w: int, h: int) -> tuple[int, int]:
    scale = min(1.0, _MAX_SIDE / max(w, h))
    nw, nh = int(w * scale), int(h * scale)
    # diffusion pipelines require dimensions divisible by 8
    return max(8, nw - nw % 8), max(8, nh - nh % 8)


def _composite(original: Image.Image, generated: Image.Image, mask: Image.Image, edge_blend: int = 0) -> Image.Image:
    """
    Put the generated pixels back only inside the mask, keeping the original
    background byte-for-byte. Guards against any drift from the resize round-trip.
    """
    generated = generated.resize(original.size, Image.LANCZOS)
    binary = mask.convert("L").resize(original.size, Image.NEAREST)
    selected = np.array(binary) > 127
    alpha = np.array(binary.filter(ImageFilter.GaussianBlur(edge_blend))) / 255.0 if edge_blend else selected.astype(float)
    alpha = np.where(selected, alpha, 0)[..., None]
    out = np.rint(alpha * np.array(generated.convert("RGB")) + (1 - alpha) * np.array(original.convert("RGB")))
    return Image.fromarray(out.astype(np.uint8), "RGB")


def run_prompt_replace(
    image: Image.Image,
    mask: Image.Image,
    prompt: str,
    negative_prompt: str | None,
    steps: int,
    guidance_scale: float,
    seed: int = 0,
    quality: str = "balanced",
    mask_growth: int = 6,
    edge_blend: int = 2,
) -> tuple[Image.Image, Image.Image | None]:
    """LaMa clean -> BrushNet paint. Returns (final_composited, stage1_cleaned)."""
    mask_d = dilate_mask(mask, iterations=mask_growth)

    # Stage 1 — remove the old object so BrushNet starts from a clean plate.
    cleaned_full = None
    if settings.prompt_clean_first:
        with model_manager.use("lama") as lama:
            cleaned_full = lama(image, mask_d)

    w, h = image.size
    ww, wh = _work_size(w, h)
    cleaned = (cleaned_full if cleaned_full is not None else image).resize((ww, wh), Image.LANCZOS)
    mask_work = mask_d.resize((ww, wh), Image.NEAREST)

    # Stage 2 — synthesize the new object described by the prompt.
    with model_manager.use("prompt_quality" if quality == "quality" else "brushnet") as inpainter:
        generator = torch.Generator(device=model_manager.device).manual_seed(seed)
        result = inpainter.inpaint(
            image=cleaned,
            mask=mask_work,
            prompt=prompt,
            negative_prompt=negative_prompt,
            steps=steps,
            guidance=guidance_scale,
            generator=generator,
        )

    final = _composite(image, result, mask_d, edge_blend)
    return final, cleaned_full


def run_reference_replace(
    image: Image.Image,
    mask: Image.Image,
    product_image: Image.Image,
    ip_scale: float,
    steps: int,
    guidance_scale: float,
    seed: int = 0,
    prompt: str | None = None,
    mask_growth: int = 6,
    edge_blend: int = 2,
) -> Image.Image:
    """SD1.5-inpainting + IP-Adapter conditioned on the catalog product photo."""
    mask_d = dilate_mask(mask, iterations=mask_growth)
    w, h = image.size
    ww, wh = _work_size(w, h)
    init = image.resize((ww, wh), Image.LANCZOS)
    mask_work = mask_d.resize((ww, wh), Image.NEAREST)

    with model_manager.use("ip_adapter") as pipe:
        pipe.set_ip_adapter_scale(ip_scale)
        generator = torch.Generator(device=model_manager.device).manual_seed(seed)
        result = pipe(
            prompt=prompt or "a piece of furniture, realistic, well lit, matching the room",
            negative_prompt="blurry, distorted, low quality, deformed",
            image=init,
            mask_image=mask_work,
            width=ww,
            height=wh,
            padding_mask_crop=settings.inpaint_crop_padding or None,
            ip_adapter_image=product_image,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            strength=0.99,
            generator=generator,
        ).images[0]

    return _composite(image, result, mask_d, edge_blend)
