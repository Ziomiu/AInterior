"""
Offline furniture-library builder — background removal for catalog product photos.

Clean, background-free cutouts make (a) CLIP embeddings describe the product
rather than its studio backdrop, and (b) IP-Adapter reference-mode fidelity higher.
This runs *offline* when you build your library, so it can use the heaviest/best
segmenter available — this is the one place SAM 3 (automatic concept segmentation)
earns its keep, even though the interactive request path deliberately uses only
SAM 2.1 clicks.

Backends (auto-detected, best first):
    --backend sam3   : SAM 3 automatic ("furniture") segmentation (if installed)
    --backend sam2   : SAM 2.1 automatic mask generator, keep the largest central mask
    --backend rembg  : rembg / u2net (lightweight, no GPU needed)

Usage:
    python scripts/build_library.py ./raw_products ./cutouts --backend sam2

Then feed ./cutouts to scripts/seed_catalog.py.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("build_library")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _apply_mask(image: Image.Image, mask: np.ndarray) -> Image.Image:
    """Composite the object onto white using a boolean HxW mask."""
    rgb = np.array(image.convert("RGB"))
    white = np.full_like(rgb, 255)
    out = np.where(mask[..., None], rgb, white)
    return Image.fromarray(out.astype(np.uint8), "RGB")


def cutout_sam2(image: Image.Image) -> np.ndarray:
    """SAM 2.1 automatic masks; keep the largest mask overlapping the image centre."""
    from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
    from sam2.build_sam import build_sam2_hf

    sam = build_sam2_hf("facebook/sam2.1-hiera-large")
    gen = SAM2AutomaticMaskGenerator(sam)
    masks = gen.generate(np.array(image.convert("RGB")))
    if not masks:
        return np.ones(image.size[::-1], dtype=bool)

    h, w = image.size[1], image.size[0]
    cy, cx = h // 2, w // 2
    central = [m for m in masks if m["segmentation"][cy, cx]]
    pick = max(central or masks, key=lambda m: m["area"])
    return pick["segmentation"].astype(bool)


def cutout_sam3(image: Image.Image) -> np.ndarray:
    """SAM 3 automatic 'furniture' segmentation (optional; requires the SAM 3 package)."""
    from sam3 import SAM3ImagePredictor  # type: ignore

    predictor = SAM3ImagePredictor.from_pretrained("facebook/sam3")
    predictor.set_image(np.array(image.convert("RGB")))
    masks, scores = predictor.predict_concept("furniture")
    best = int(np.argmax(scores))
    return masks[best].astype(bool)


def cutout_rembg(image: Image.Image) -> np.ndarray:
    """rembg / u2net alpha matte -> boolean mask. CPU-friendly, no SAM needed."""
    from rembg import remove

    cut = remove(image.convert("RGBA"))
    alpha = np.array(cut)[..., 3]
    return alpha > 127


BACKENDS = {"sam3": cutout_sam3, "sam2": cutout_sam2, "rembg": cutout_rembg}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path, help="Folder of raw product photos")
    ap.add_argument("dst", type=Path, help="Output folder for white-background cutouts")
    ap.add_argument("--backend", choices=list(BACKENDS), default="sam2")
    args = ap.parse_args()

    args.dst.mkdir(parents=True, exist_ok=True)
    cutout = BACKENDS[args.backend]
    images = [p for p in sorted(args.src.iterdir()) if p.suffix.lower() in IMAGE_EXTS]

    for p in images:
        try:
            img = Image.open(p)
            mask = cutout(img)
            _apply_mask(img, mask).save(args.dst / f"{p.stem}.png")
            logger.info("cutout %s (%s)", p.name, args.backend)
        except Exception as exc:  # noqa: BLE001
            logger.error("failed %s: %s", p.name, exc)

    logger.info("Done. Cutouts in %s — feed them to scripts/seed_catalog.py", args.dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
