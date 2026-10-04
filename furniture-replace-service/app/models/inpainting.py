"""
Inpainting / replacement models.

Two replacement strategies, exactly as the research phase settled:

  prompt mode   — LaMa cleans the masked region (removes the old object cleanly),
                  then BrushNet paints the new object described by the text prompt.
                  Two stages because BrushNet preserves the untouched background far
                  better when it starts from an already-clean plate (best SSIM/LPIPS
                  of the five approaches benchmarked).

  reference mode — SD1.5-inpainting + IP-Adapter, conditioned on a catalog product
                  photo. Text can't reproduce a *specific* product; image
                  conditioning at ip_scale≈0.85 does.

Each model is registered with the ModelManager as its own heavy entry so only one
sits on the GPU at a time. The two-stage prompt path acquires "lama" then
"brushnet" sequentially inside a single job — the manager swaps them on the GPU.
"""
from __future__ import annotations

import logging

import torch
from PIL import Image

from app.config import settings
from app.models.manager import model_manager

logger = logging.getLogger("inpainting")


def _dtype() -> torch.dtype:
    return torch.float16 if (settings.device == "cuda" and torch.cuda.is_available()) else torch.float32


# ── LaMa (stage 1 of prompt mode) ────────────────────────────────────────────

class LaMaCleaner:
    """Wraps simple-lama-inpainting so it fits the CPU<->GPU movement contract."""

    def __init__(self, model) -> None:
        self.model = model            # SimpleLama instance
        self.device = "cpu"

    def to(self, device: str) -> "LaMaCleaner":
        self.model.model.to(device)   # SimpleLama keeps the JIT net on .model
        self.model.device = torch.device(device)
        self.device = device
        return self

    def __call__(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        # SimpleLama expects a white (255) region to remove on a black background.
        return self.model(image, mask.convert("L"))


def _load_lama() -> LaMaCleaner:
    from simple_lama_inpainting import SimpleLama

    lama = SimpleLama(device=torch.device("cpu"))
    return LaMaCleaner(lama)


# ── BrushNet (stage 2 of prompt mode) ────────────────────────────────────────

class PromptInpainter:
    def __init__(self, pipe, backend: str) -> None:
        self.pipe = pipe
        self.backend = backend

    def to(self, device: str) -> "PromptInpainter":
        self.pipe.to(device)
        return self

    def inpaint(self, *, image, mask, prompt, negative_prompt, steps, guidance, generator):
        options = {}
        if self.backend == "brushnet":
            image = Image.composite(Image.new("RGB", image.size), image, mask.convert("L"))
            mask = mask.convert("RGB")
        elif settings.inpaint_crop_padding:
            options["padding_mask_crop"] = settings.inpaint_crop_padding
        return self.pipe(
            image=image,
            mask_image=mask,
            width=image.width,
            height=image.height,
            prompt=prompt,
            negative_prompt=negative_prompt,
            num_inference_steps=steps,
            guidance_scale=guidance,
            generator=generator,
            **options,
        ).images[0]


def _load_brushnet():
    """
    BrushNet inpainting pipeline (SD1.5 base + BrushNet conditioning branch).

    BrushNet is not in core diffusers; it ships as a community pipeline plus a
    BrushNetModel checkpoint. Point settings.brushnet_model at the local
    checkpoint dir (see download_models.sh / README).
    """
    try:
        from diffusers import StableDiffusionBrushNetPipeline, BrushNetModel
    except ImportError:
        from diffusers import AutoPipelineForInpainting

        model_id = settings.prompt_inpaint_model or settings.sd_inpaint_model
        logger.warning("BrushNet classes unavailable; prompt backend is stock inpainting: %s", model_id)
        pipe = AutoPipelineForInpainting.from_pretrained(
            model_id,
            torch_dtype=_dtype(),
            variant=settings.sd_inpaint_variant,
            use_safetensors=True,
            safety_checker=None,
            requires_safety_checker=False,
        )
        pipe.set_progress_bar_config(disable=True)
        backend = "sdxl" if "XL" in type(pipe).__name__ else "sd15"
        return PromptInpainter(pipe, backend)

    from diffusers import UniPCMultistepScheduler

    dtype = _dtype()
    brushnet = BrushNetModel.from_pretrained(settings.brushnet_model, torch_dtype=dtype)
    pipe = StableDiffusionBrushNetPipeline.from_pretrained(
        settings.brushnet_base_model,
        brushnet=brushnet,
        torch_dtype=dtype,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
    pipe.set_progress_bar_config(disable=True)
    pipe.enable_attention_slicing()
    return PromptInpainter(pipe, "brushnet")


# ── IP-Adapter (reference mode) ──────────────────────────────────────────────

def _load_ip_adapter():
    from diffusers import AutoPipelineForInpainting

    dtype = _dtype()
    pipe = AutoPipelineForInpainting.from_pretrained(
        settings.sd_inpaint_model,
        torch_dtype=dtype,
        variant=settings.sd_inpaint_variant,
        use_safetensors=True,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe.load_ip_adapter(
        settings.ip_adapter_repo,
        subfolder=settings.ip_adapter_subfolder,
        weight_name=settings.ip_adapter_weight,
    )
    pipe.set_progress_bar_config(disable=True)
    return pipe


def _load_quality_inpainter():
    from diffusers import AutoPipelineForInpainting

    pipe = AutoPipelineForInpainting.from_pretrained(
        "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
        torch_dtype=_dtype(), variant="fp16", use_safetensors=True,
    )
    pipe.set_progress_bar_config(disable=True)
    return PromptInpainter(pipe, "sdxl")


def register_inpainting_models() -> None:
    model_manager.register("lama", _load_lama, lambda m, dev: m.to(dev))
    model_manager.register("brushnet", _load_brushnet, lambda p, dev: p.to(dev))
    model_manager.register("ip_adapter", _load_ip_adapter, lambda p, dev: p.to(dev))
    model_manager.register("prompt_quality", _load_quality_inpainter, lambda p, dev: p.to(dev))
